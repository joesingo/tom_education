from datetime import datetime
import json
import os.path

from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.db.utils import IntegrityError
from django.utils.http import urlencode
from django.views.generic.edit import FormMixin
from django.shortcuts import redirect, reverse
from tom_dataproducts.models import DataProduct
from tom_observations.views import ObservationCreateView
from tom_targets.views import TargetDetailView

from tom_education.forms import make_templated_form, TimelapseCreateForm
from tom_education.models import ObservationTemplate
from tom_education.timelapse import Timelapse


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


class TimelapseTargetDetailView(FormMixin, TargetDetailView):
    """
    Extend the target detail view to add a form to create a timelapse from data
    products
    """
    form_class = TimelapseCreateForm

    def get_success_url(self):
        return reverse('tom_targets:detail', kwargs={'pk': self.get_object().pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['target'] = self.get_object()
        return kwargs

    def get_context_data(self, *args, **kwargs):
        self.object = self.get_object()
        context = super().get_context_data(*args, **kwargs)
        context['timelapse_form'] = self.get_form()
        return context

    def post(self, _request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def form_valid(self, form):
        # Construct set of data products that were selected
        products = {
            DataProduct.objects.get(product_id=pid)
            for pid, checked in form.cleaned_data.items() if checked
        }
        tl = Timelapse(products)
        product = tl.create_dataproduct()
        msg = 'Timelapse \'{}\' created successfully'.format(
            os.path.basename(product.data.name)
        )
        messages.success(self.request, msg)
        return super().form_valid(form)
