from datetime import datetime
from io import BytesIO
import json
import os.path

from django.core.exceptions import PermissionDenied
from django.core.files import File
from django.conf import settings
from django.contrib import messages
from django.db.utils import IntegrityError
from django.utils.http import urlencode
from django.views.generic.edit import FormMixin
from django.shortcuts import redirect, reverse
from tom_dataproducts.models import DataProduct, IMAGE_FILE
from tom_observations.views import ObservationCreateView
from tom_targets.views import TargetDetailView

from tom_education.forms import make_templated_form, TimelapseCreateForm
from tom_education.models import ObservationTemplate, TimelapseDataProduct, TIMELAPSE_PENDING
from tom_education.timelapse import Timelapse, DateFieldNotFoundError


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
        # Form is not rendered in the template, so add form errors as messages
        # Note: this discards information about which field each error relates
        # to, since errors are not field-specific for the timelapse form
        for err_list in form.errors.values():
            for err_msg in err_list:
                messages.error(self.request, err_msg)
        return self.form_invalid(form)

    def form_valid(self, form):
        response = super().form_valid(form)
        # Construct set of data products that were selected
        products = {
            DataProduct.objects.get(product_id=pid)
            for pid, checked in form.cleaned_data.items() if checked
        }

        try:
            tl_settings = settings.TOM_EDUCATION_TIMELAPSE_SETTINGS
        except AttributeError:
            tl_settings = {}
        fmt = tl_settings.get('format', 'gif')
        fps = tl_settings.get('fps', 10)

        # Create a TimelapseDataProduct
        target = self.get_object()
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d-%H%M%S')
        product_id = 'timelapse_{}_{}'.format(target.identifier, date_str)
        filename = '{}.{}'.format(product_id, fmt)

        tl_prod = TimelapseDataProduct.objects.create(
            product_id=product_id,
            target=target,
            tag=IMAGE_FILE[0],
            status=TIMELAPSE_PENDING
        )
        # Save empty file in data attribute
        tl_prod.data.save(filename, File(BytesIO()))
        tl_prod.frames.add(*products)
        tl_prod.save()

        # TODO: do this in a job queue
        product_pks = {prod.pk for prod in products}
        try:
            tl = Timelapse(product_pks, fmt, fps)
        except DateFieldNotFoundError as ex:
            messages.error(self.request, 'Could not find observation date in \'{}\''.format(ex))
            return response

        tl.write(tl_prod, filename)
        msg = 'Timelapse \'{}\' created successfully'.format(
            os.path.basename(tl_prod.data.name)
        )
        messages.success(self.request, msg)
        return response
