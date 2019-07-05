from datetime import datetime
import json

from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.db.utils import IntegrityError
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils.http import urlencode
from django.views.generic import ListView
from django.views.generic.edit import FormMixin
from django.shortcuts import redirect, reverse
from tom_dataproducts.models import DataProduct
from tom_observations.views import ObservationCreateView
from tom_targets.models import Target
from tom_targets.views import TargetDetailView

from tom_education.forms import make_templated_form, DataProductActionForm
from tom_education.models import (
    ObservationTemplate, TimelapseDataProduct, TIMELAPSE_PENDING, TIMELAPSE_CREATED,
    TIMELAPSE_FAILED
)
from tom_education.tasks import make_timelapse


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
        # Construct set of data products that were selected
        products = {
            DataProduct.objects.get(product_id=pid)
            for pid, checked in form.cleaned_data.items() if pid in form.product_ids and checked
        }
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

    def handle_view_gallery(self, products, form):
        return JsonResponse({'prods': [p.pk for p in products], 'action': 'view that gallery!'})


class TimelapseStatusApiView(ListView):
    """
    View that finds all TimelapseDataProduct objects associated with a
    specified Target, groups them by status, and returns the listing in a JSON
    response
    """
    def get_queryset(self):
        target = Target.objects.get(pk=self.kwargs['target'])
        return TimelapseDataProduct.objects.filter(target=target)

    def get(self, request, *args, **kwargs):
        statuses = (TIMELAPSE_PENDING, TIMELAPSE_CREATED, TIMELAPSE_FAILED)
        response_dict = {
            'ok': True,
            'timelapses': {status: [] for status in statuses}
        }

        try:
            qs = self.get_queryset()
        except Target.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'Target not found'}, status=404)

        for tl_prod in qs:
            prod_dict = {
                'product_id': tl_prod.product_id,
                'filename': tl_prod.get_filename()
            }
            if tl_prod.status == TIMELAPSE_FAILED:
                prod_dict['failure_message'] = tl_prod.failure_message or None

            response_dict['timelapses'][tl_prod.status].append(prod_dict)
        # Sort each list by product ID so we have a consistent order
        for status in statuses:
            response_dict['timelapses'][status].sort(key=lambda d: d['product_id'])
        return JsonResponse(response_dict)
