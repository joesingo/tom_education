from dataclasses import dataclass
from datetime import datetime
import json
from typing import Iterable
import csv
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.utils import IntegrityError
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseRedirect, Http404, HttpResponse
from django.shortcuts import redirect, reverse
from django.utils.http import urlencode
from django.views.generic import FormView, TemplateView
from django.views.generic.detail import DetailView
from django.views.generic.edit import FormMixin
from tom_dataproducts.models import DataProduct, ObservationRecord, ReducedDatum
from tom_observations.facility import get_service_class
from tom_observations.views import ObservationCreateView
from tom_targets.models import (
    Target, GLOBAL_TARGET_FIELDS, REQUIRED_NON_SIDEREAL_FIELDS,
    REQUIRED_NON_SIDEREAL_FIELDS_PER_SCHEME
)
from tom_targets.views import TargetDetailView, TargetCreateView, TargetUpdateView
from rest_framework.exceptions import NotFound
from rest_framework.generics import CreateAPIView, ListAPIView, RetrieveAPIView
from rest_framework import serializers
from rest_framework.response import Response

from tom_education.forms import make_templated_form, DataProductActionForm, GalleryForm
from tom_education.models import (
    AsyncProcess,
    ASYNC_STATUS_CREATED,
    ObservationAlert,
    ObservationTemplate,
    PipelineProcess,
    TimelapsePipeline,
)
from tom_education.serializers import (
    AsyncProcessSerializer,
    ObservationAlertSerializer,
    PipelineProcessSerializer,
    TargetDetailSerializer,
    TimestampField,
)
from tom_education.tasks import run_pipeline, send_task

logger = logging.getLogger(__name__)

class TemplatedObservationCreateView(ObservationCreateView):
    supported_facilities = ('LCO',)

    def get_form_class(self):
        return make_templated_form(super().get_form_class())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get extra context data from the form object, if applicable
        form = context['form']
        if hasattr(form, 'get_extra_context'):
            context.update(form.get_extra_context())
        context['target'] = self.get_target()
        return context

    def serialize_fields(self, form):
        return json.dumps(form.cleaned_data)

    def form_url(self):
        """
        Return the URL for this form view for the current facility and target
        """
        base = reverse("tom_education:create_obs", kwargs={'facility': self.get_facility()})
        return base + '?' + urlencode({'target_id': self.get_target_id()})

    def can_create_template(self):
        """
        Return True if the current user can create a template for the current
        facility, and False otherwise
        """
        supported_facility = self.get_facility() in self.supported_facilities
        return supported_facility and self.request.user.is_staff

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['form_url'] = self.form_url()
        kwargs['show_create'] = self.can_create_template()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()

        facility = self.get_facility()
        template_id = self.request.GET.get('template_id')
        if template_id:
            template = ObservationTemplate.objects.filter(
                target=self.get_target(),
                facility=facility
            ).get(pk=template_id)

            initial.update(json.loads(template.fields))
            # Set identifier field to something unique based on the template
            id_field = ObservationTemplate.get_identifier_field(facility)
            initial[id_field] = template.get_identifier()

            # Dates need to be converted to just YYYY-MM-DD to display in the
            # widget properly
            for field in ObservationTemplate.get_date_fields(facility):
                dt = initial[field]
                initial[field] = datetime.fromisoformat(dt).strftime('%Y-%m-%d')

        return initial

    def form_valid(self, form):
        facility = self.get_facility()
        if self.get_form_class().new_template_action[0] in form.data:
            if not self.can_create_template():
                raise PermissionDenied()

            # Create new template
            # TODO: deal with None below
            name = form.cleaned_data.get(ObservationTemplate.get_identifier_field(facility))
            try:
                template = ObservationTemplate.objects.create(
                    name=name,
                    target=self.get_target(),
                    facility=facility,
                    fields=self.serialize_fields(form)
                )
            except IntegrityError:
                form.add_error(None, 'Template name "{}" already in use'.format(name))
                return self.form_invalid(form)

            path = template.get_create_url(self.form_url())
            return redirect(path)

        return super().form_valid(form)


class ActionableTargetDetailView(FormMixin, TargetDetailView):
    """
    Extend the target detail view to add a form to select a group of data
    products and perform an action on them.

    A method `handle_<name>(products, form)` is called to handle the form
    submission, where `<name>` is the value of the action field in the form.
    """
    form_class = DataProductActionForm
    template_name = "tom_targets/target_dataview.html"

    def get_success_url(self):
        return reverse('tom_targets:detail', kwargs={'pk': self.get_object().pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['target'] = self.get_object()
        return kwargs

    def get_context_data(self, *args, **kwargs):
        self.object = self.get_object()
        context = super().get_context_data(*args, **kwargs)
        context['dataproducts_form'] = self.get_form()
        context['pipeline_names'] = sorted(PipelineProcess.get_available().keys())
        context['pipeline_flags'] = {}
        for name in context['pipeline_names']:
            pipeline_cls = PipelineProcess.get_subclass(name)
            if pipeline_cls.flags:
                context['pipeline_flags'][name] = pipeline_cls.flags

        return context

    def post(self, _request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        # Form is not rendered in the template, so add form errors as messages
        # Note: this discards information about which field each error relates
        # to
        for err_list in form.errors.values():
            for err_msg in err_list:
                messages.error(self.request, err_msg)
        return self.form_invalid(form)

    def form_valid(self, form):
        products = form.get_selected_products()
        try:
            method = getattr(self, 'handle_{}'.format(form.data['action']))
        except AttributeError:
            return HttpResponseBadRequest('Invalid action \'{}\''.format(form.data['action']))
        return method(products, form)

    def handle_pipeline(self, products, form):
        try:
            name = form.data['pipeline_name']
        except KeyError:
            return HttpResponseBadRequest('No pipeline_name given')
        try:
            pipeline_cls = PipelineProcess.get_subclass(name)
        except KeyError:
            return HttpResponseBadRequest("Invalid pipeline name '{}'".format(name))

        # Get pipeline-specific flags. Initially set all to False; those
        # present in form data will be set to True
        flags = {f: False for f in pipeline_cls.flags} if pipeline_cls.flags else {}
        for key in form.data:
            prefix = 'pipeline_flag_'
            if not key.startswith(prefix):
                continue
            flag = key[len(prefix):]
            if flag not in flags:
                continue
            flags[flag] = True

        target = self.get_object()
        pipe = pipeline_cls.create_timestamped(target, products, flags)
        send_task(run_pipeline, pipe, name)
        return JsonResponse({'ok': True})

    def handle_view_gallery(self, products, form):
        # Redirect to gallery page with product PKs as GET params
        product_pks = [str(p.pk) for p in products]
        base = reverse('tom_education:gallery')
        url = base + '?' + urlencode({'product_pks': ",".join(product_pks)})
        return redirect(url)

    def handle_delete(self, products, form):
        product_pks = [str(p.pk) for p in products]
        base = reverse('tom_education:delete_dataproducts')
        url = base + '?' + urlencode({'product_pks': ",".join(product_pks)})
        return redirect(url)


class GalleryView(FormView):
    """
    Show thumbnails for a number of data products and allow the user to add a
    selection of them to a data product group
    """
    form_class = GalleryForm
    template_name = 'tom_education/gallery.html'

    def get_pks_string(self):
        """
        Return comma separated string of products PKs from GET or POST params
        """
        if self.request.method == 'GET':
            obj = self.request.GET
        else:
            obj = self.request.POST
        return obj.get('product_pks', '')

    def get_products(self, pks_string):
        try:
            return self._products
        except AttributeError:
            pass

        if pks_string:
            pks = pks_string.split(',')
            self._products = {DataProduct.objects.get(pk=int(pk)) for pk in pks}
        else:
            self._products = set([])
        return self._products

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['products'] = self.get_products(self.get_pks_string())
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Comma separated PK string is required to construct form instance, so
        # must be send in the POST request too. Put it in the context so it
        # can be sent as a hidden field
        pks_string = self.get_pks_string()
        context['product_pks'] = pks_string

        products = self.get_products(pks_string)
        if products:
            context['products'] = products
            context['show_form'] = True
        else:
            messages.error(self.request, 'No data products provided')
        return context

    def form_valid(self, form):
        selected = form.get_selected_products()
        group = form.cleaned_data['group']
        for product in selected:
            product.group.add(group)
            product.save()

        # Redirect to group detail view
        msg = 'Added {} data products to group \'{}\''.format(len(selected), group.name)
        messages.success(self.request, msg)
        url = reverse('tom_dataproducts:group-detail', kwargs={'pk': group.pk})
        return HttpResponseRedirect(url)


class AsyncStatusApi(ListAPIView):
    """
    View that finds all AsyncProcess objects associated with a specified Target
    and returns the listing in a JSON response
    """
    serializer_class = AsyncProcessSerializer

    def get_queryset(self):
        try:
            target = Target.objects.get(pk=self.kwargs['target'])
        except Target.DoesNotExist:
            raise Http404
        return AsyncProcess.objects.filter(target=target).order_by('-created')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        timestamp = TimestampField().to_representation(datetime.now())
        return Response({'timestamp': timestamp, 'processes': serializer.data})


class PipelineProcessDetailView(DetailView):
    model = PipelineProcess

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.target:
            context['target_url'] = reverse('tom_targets:detail', kwargs={'pk': self.object.target.pk})
        return context


class PipelineProcessApi(RetrieveAPIView):
    """
    Return information about a PipelineProcess in a JSON response
    """
    queryset = PipelineProcess.objects.all()
    serializer_class = PipelineProcessSerializer


@dataclass
class TargetDetailApiInfo:
    """
    Wrapper object containing a target and its timelapses, for serialization
    for the target detail API
    """
    target: Target
    timelapses: Iterable[TimelapsePipeline]
    data: Target


class TargetDetailApiView(RetrieveAPIView):
    """
    Return information about a target and its timelapses, and return a JSON
    response
    """
    serializer_class = TargetDetailSerializer
    # Note: we specify a Target queryset to make use of rest_framework methods
    # to retrieve Target model from the PK kwarg in URL, but it is NOT a Target
    # object that will be serialized
    queryset = Target.objects.all()

    def get_object(self):
        target = super().get_object()
        tl_pipelines = TimelapsePipeline.objects.filter(
            target=target, group__dataproduct__target__isnull=False,
            status=ASYNC_STATUS_CREATED,
            process_type='TimelapsePipeline'
        ).order_by('-terminal_timestamp')
        return TargetDetailApiInfo(target=target, timelapses=tl_pipelines, data=target)


class ObservationAlertApiCreateView(CreateAPIView):
    """
    Create an ObservationAlert by instantiating an ObservationTemplate for a
    given target
    """
    throttle_scope = 'observe'

    serializer_class = ObservationAlertSerializer

    def perform_create(self, serializer):
        data = serializer.validated_data
        try:
            target = Target.objects.get(pk=data['target'])
            facility_class = get_service_class(data['facility'])
            template = ObservationTemplate.objects.get(
                target=target,
                name=data['template_name'],
                facility=data['facility']
            )
        except Target.DoesNotExist:
            raise NotFound(detail='Target not found.')
        except ImportError:
            raise NotFound(detail='Facility not found.')
        except ObservationTemplate.DoesNotExist:
            err = "Template '{}' not found for target '{}' and facility '{}'".format(
                data['template_name'], target.name, data['facility']
            )
            raise NotFound(detail=err)

        # Construct form for creating an observation
        form_data = {
            'target_id': target.pk,
            'facility': facility_class.name
        }
        form_data.update(json.loads(template.fields))
        id_field = ObservationTemplate.get_identifier_field(facility_class.name)
        form_data[id_field] = template.get_identifier()
        form_data.update(data.get('overrides', {}))
        form = facility_class.get_form(None)(form_data)  # observation type is not relevant to us
        if not form.is_valid():
            raise serializers.ValidationError(form.errors)

        # Submit observation using facility class
        observation_ids = facility_class().submit_observation(form.observation_payload())
        assert len(observation_ids) == 1, (
            'Submittion created multiple observation IDs: {}'.format(observation_ids)
        )
        # Create Observation record and alert
        ob = ObservationRecord.objects.create(
            target=target,
            facility=facility_class.name,
            parameters=form.serialize_parameters(),
            observation_id=observation_ids[0]
        )
        ObservationAlert.objects.create(email=data['email'], observation=ob)


class DataProductDeleteMultipleView(LoginRequiredMixin, TemplateView):
    template_name = 'tom_education/dataproduct_confirm_delete_multiple.html'

    def get_products(self, pks_string):
        pks = pks_string.split(',')
        return {DataProduct.objects.get(pk=int(pk)) for pk in pks}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['next'] = self.request.META.get('HTTP_REFERER', '/')
            context['product_pks'] = self.request.GET.get('product_pks', '')
            context['to_delete'] = self.get_products(context['product_pks'])
        return context

    def post(self, request, *args, **kwargs):
        prods = self.get_products(self.request.POST.get('product_pks', []))
        for prod in prods:
            ReducedDatum.objects.filter(data_product=prod).delete()
            prod.data.delete()
            prod.delete()
        messages.success(request, 'Deleted {} data products'.format(len(prods)))
        return HttpResponseRedirect(self.request.POST.get('next', '/'))


class NonSiderealFieldsMixin:
    """
    Mixin for views which adds information to the template context about the
    required fields per scheme for non-sidereal targets. This allows client
    side JS to hide fields which are not applicable for the selected scheme.

    Relies on the view having a method get_target_type() which returns
    Target.SIDEREAL or Target.NON_SIDEREAL
    """
    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        if self.get_target_type() == Target.NON_SIDEREAL:
            form = self.get_form()

            # Build list of base fields that should always be shown, including
            # non-model fields declared in the form itself and extra fields
            declared = list(form.declared_fields.keys())
            extra = list(getattr(form, 'extra_fields', {}).keys())
            base = GLOBAL_TARGET_FIELDS + REQUIRED_NON_SIDEREAL_FIELDS + declared + extra

            context['non_sidereal_fields'] = json.dumps({
                'base_fields': base,
                'scheme_fields': REQUIRED_NON_SIDEREAL_FIELDS_PER_SCHEME,
            })
        return context


class EducationTargetCreateView(NonSiderealFieldsMixin, TargetCreateView):
    pass


class EducationTargetUpdateView(NonSiderealFieldsMixin, TargetUpdateView):
    def get_target_type(self):
        return self.object.type


def photometry_to_csv(request, pk):
    # Create the HttpResponse object with the appropriate CSV header.
    target = Target.objects.get(pk=pk)
    filename = target.name.replace(' ','_').replace('.','_')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'

    rdata = ReducedDatum.objects.filter(target=target, data_type='photometry').order_by('timestamp')
    writer = csv.writer(response)
    for rdatum in rdata:
        try:
            vals = json.loads(rdatum.value)
        except json.decoder.JSONDecodeError:
            logger.warning(f'Could not parse {rdatum.value} of {target.name}')
        writer.writerow([rdatum.timestamp.isoformat('T'), vals['magnitude'], vals['error']])

    return response
