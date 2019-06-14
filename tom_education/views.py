from datetime import datetime
import json

from django.core.exceptions import PermissionDenied
from django.utils.http import urlencode
from django.shortcuts import redirect, reverse
from tom_observations.views import ObservationCreateView

from tom_education.forms import make_templated_form
from tom_education.models import ObservationTemplate


class TemplatedObservationCreateView(ObservationCreateView):

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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instantiate_template_url'] = self.instantiate_template_url()
        kwargs['show_create'] = self.request.user.is_staff
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
            if not self.request.user.is_staff:
                raise PermissionDenied()

            # Create new template
            template = ObservationTemplate.objects.create(
                name=form.cleaned_data.get(self.get_identifier_field()),  # TODO: deal with None
                target=self.get_target(),
                facility=self.get_facility(),
                fields=self.serialize_fields(form)
            )
            path = template.get_create_url(self.instantiate_template_url())
            return redirect(path)

        return super().form_valid(form)
