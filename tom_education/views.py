from datetime import datetime
import json

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.utils import IntegrityError
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import redirect, reverse
from django.utils.http import urlencode
from django.views.generic import ListView, FormView
from django.views.generic.detail import DetailView
from django.views.generic.edit import FormMixin
from tom_dataproducts.models import DataProduct
from tom_observations.views import ObservationCreateView
from tom_targets.models import Target
from tom_targets.views import TargetDetailView

from tom_education.forms import make_templated_form, DataProductActionForm, GalleryForm
from tom_education.models import (
    AsyncProcess, AutovarProcess, PipelineProcess, ObservationTemplate,
    TimelapseDataProduct, ASYNC_STATUS_PENDING, ASYNC_STATUS_CREATED,
    ASYNC_STATUS_FAILED, ASYNC_TERMINAL_STATES
)
from tom_education.tasks import run_pipeline, make_timelapse


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
            if PipelineProcess not in getattr(pipeline_cls, '__bases__', []):
                raise ImportError
        except (KeyError, ImportError):
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


class AsyncStatusApi(ListView):
    """
    View that finds all AsyncProcess objects associated with a specified Target
    and returns the listing in a JSON response
    """
    def get_queryset(self):
        target = Target.objects.get(pk=self.kwargs['target'])
        return AsyncProcess.objects.filter(target=target)

    def get(self, request, *args, **kwargs):
        statuses = (ASYNC_STATUS_PENDING, ASYNC_STATUS_CREATED, ASYNC_STATUS_FAILED)
        response_dict = {
            'ok': True,
            'timestamp': datetime.now().timestamp(),
            'processes': []
        }

        try:
            qs = self.get_queryset()
        except Target.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'Target not found'}, status=404)

        for process in qs:
            proc_dict = {
                'identifier': process.identifier,
                'created': process.created.timestamp(),
                'status': process.status
            }
            if process.status == ASYNC_STATUS_FAILED:
                proc_dict['failure_message'] = process.failure_message or None
            if process.terminal_timestamp:
                proc_dict['terminal_timestamp'] = process.terminal_timestamp.timestamp()
            # Special case for PipelineProcess objects: provide link to detail view
            if hasattr(process, 'pipelineprocess'):
                view_url = reverse('tom_education:pipeline_detail', kwargs={'pk': process.pk})
                proc_dict['view_url'] = view_url

            response_dict['processes'].append(proc_dict)

        # Sort processes by creation time (most recent first)
        response_dict['processes'].sort(key=lambda d: d['created'], reverse=True)
        return JsonResponse(response_dict)


class PipelineProcessDetailView(DetailView):
    model = PipelineProcess

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.target:
            context['target_url'] = reverse('tom_targets:detail', kwargs={'pk': self.object.target.pk})
        return context


class PipelineProcessApi(DetailView):
    """
    Return information about a PipelineProcess in a JSON response
    """
    model = PipelineProcess

    def get_object(self, **kwargs):
        pk = self.kwargs.get(self.pk_url_kwarg)
        return self.get_queryset().get(pk=pk)

    def get(self, request, *args, **kwargs):
        try:
            process = self.get_object()
        except PipelineProcess.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'Pipeline process not found'}, status=404)

        response_dict = {
            'ok': True,
            'identifier': process.identifier,
            'created': process.created.timestamp(),
            'status': process.status,
            'logs': process.logs or ''
        }
        if process.status == ASYNC_STATUS_FAILED:
            response_dict['failure_message'] = process.failure_message or None
        if process.terminal_timestamp:
            response_dict['terminal_timestamp'] = process.terminal_timestamp.timestamp()
        if process.group:
            kwargs = {'pk': process.group.pk}
            response_dict['group_name'] = process.group.name
            response_dict['group_url'] = reverse('tom_dataproducts:group-detail', kwargs=kwargs)

        return JsonResponse(response_dict)
