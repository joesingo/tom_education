from dataclasses import dataclass
from datetime import datetime
import json
from typing import Iterable

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.utils import IntegrityError
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseRedirect, Http404
from django.shortcuts import redirect, reverse
from django.utils.http import urlencode
from django.views.generic import FormView
from django.views.generic.detail import DetailView
from django.views.generic.edit import FormMixin
from tom_dataproducts.models import DataProduct
from tom_observations.views import ObservationCreateView
from tom_targets.models import Target
from tom_targets.views import TargetDetailView
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework import serializers
from rest_framework.response import Response

from tom_education.forms import make_templated_form, DataProductActionForm, GalleryForm
from tom_education.models import (
    AsyncProcess, PipelineProcess, ObservationTemplate, TimelapseDataProduct,
    ASYNC_STATUS_PENDING, ASYNC_STATUS_CREATED, ASYNC_STATUS_FAILED,
    ASYNC_TERMINAL_STATES
)
from tom_education.serializers import (
    AsyncProcessSerializer, PipelineProcessSerializer, TimestampField,
    TargetDetailSerializer
)
from tom_education.tasks import run_pipeline, make_timelapse
from tom_education.templatetags.dataproduct_extras import exclude_non_created_timelapses


class TemplatedObservationCreateView(ObservationCreateView):
    supported_facilities = ('LCO',)

    def get_form_class(self):
        return make_templated_form(super().get_form_class())

    def get_identifier_field(self):
        """
        Return name of the field used to extract template name when creating a
        template
        """
        if self.get_facility() == 'LCO':
            return 'group_id'
        raise NotImplementedError

    def get_date_fields(self):
        if self.get_facility() == 'LCO':
            return ['start', 'end']
        return []

    def serialize_fields(self, form):
        return json.dumps(form.cleaned_data)

    def instantiate_template_url(self):
        """
        Return the URL which renders the form with a template instantiated
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
        kwargs['instantiate_template_url'] = self.instantiate_template_url()
        kwargs['show_create'] = self.can_create_template()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()

        template_id = self.request.GET.get('template_id')
        if template_id:
            template = ObservationTemplate.objects.filter(
                target=self.get_target(),
                facility=self.get_facility()
            ).get(pk=template_id)

            initial.update(json.loads(template.fields))
            # Set identifier field to something unique based on the template name
            initial[self.get_identifier_field()] = template.get_identifier()

            # Dates need to be converted to just YYYY-MM-DD to display in the
            # widget properly
            for field in self.get_date_fields():
                dt = initial[field]
                initial[field] = datetime.fromisoformat(dt).strftime('%Y-%m-%d')

        return initial

    def form_valid(self, form):
        if self.get_form_class().new_template_action[0] in form.data:
            if not self.can_create_template():
                raise PermissionDenied()

            # Create new template
            name = form.cleaned_data.get(self.get_identifier_field())  # TODO: deal with None
            try:
                template = ObservationTemplate.objects.create(
                    name=name,
                    target=self.get_target(),
                    facility=self.get_facility(),
                    fields=self.serialize_fields(form)
                )
            except IntegrityError:
                form.add_error(None, 'Template name "{}" already in use'.format(name))
                return self.form_invalid(form)

            path = template.get_create_url(self.instantiate_template_url())
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

    def handle_create_timelapse(self, products, form):
        target = self.get_object()
        tl_prod = TimelapseDataProduct.create_timestamped(target, products)
        make_timelapse.send(tl_prod.pk)
        return JsonResponse({'ok': True})

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
        for key, val in form.data.items():
            prefix = 'pipeline_flag_'
            if not key.startswith(prefix):
                continue
            flag = key[len(prefix):]
            if flag not in flags:
                continue
            flags[flag] = True

        target = self.get_object()

        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d-%H%M%S')
        code = pipeline_cls.short_name
        identifier = f'{code}_{target.identifier}_{date_str}'
        process = pipeline_cls.objects.create(
            identifier=identifier,
            target=target,
            flags_json=json.dumps(flags),
        )
        process.input_files.add(*products)
        process.save()
        run_pipeline.send(process.pk, name)
        return JsonResponse({'ok': True})

    def handle_view_gallery(self, products, form):
        # Redirect to gallery page with product PKs as GET params
        product_pks = [str(p.pk) for p in products]
        base = reverse('tom_education:gallery')
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
    timelapses: Iterable[TimelapseDataProduct]


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
        all_timelapses = TimelapseDataProduct.objects.filter(target=target).order_by('fmt')
        timelapses = exclude_non_created_timelapses(all_timelapses)
        return TargetDetailApiInfo(target=target, timelapses=timelapses)
