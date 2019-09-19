from django import forms
from django.core.exceptions import ValidationError
from tom_dataproducts.models import DataProduct, DataProductGroup

from tom_education.models import ObservationTemplate


def make_templated_form(base_class):
    """
    Return a sub-class of `base_class` which additionally provides links to
    create and instantiate templates.

    `base_class` should be a sub-class of
    tom_observations.facility.GenericObservationForm.
    """
    class F(base_class):
        # Param name for submit button in form, and text for the button
        new_template_action = ('create-template', 'Create new template')

        def __init__(self, *args, **kwargs):
            self.form_url = kwargs.pop('form_url')
            self.show_create = kwargs.pop('show_create')
            super().__init__(*args, **kwargs)

            # If the base form uses crispy, modify the form helper to not
            # include outer <form> tags (since we include these manually in the
            # template)
            if hasattr(self, 'helper'):
                self.helper.form_tag = None

        def get_extra_context(self):
            context = super().get_extra_context()

            # Add template names and instantiation URLs to the context
            templates = ObservationTemplate.objects.filter(
                target__pk=self.initial['target_id'],
                facility=self.initial['facility']
            )
            context['templates'] = []
            for template in templates:
                url = template.get_create_url(self.form_url)
                name = template.name
                context['templates'].append((name, url))

            # Add info for button to create new template
            context['show_new_template_action'] = self.show_create
            context['new_template_action_button'] = self.new_template_action
            return context

    return F


class DataProductSelectionForm(forms.Form):
    """
    Base class for a form including a list of data product checkboxes, where
    the list of data products is taken from the 'products' kwarg to __init__
    """
    def __init__(self, *args, **kwargs):
        products = kwargs.pop('products')
        super().__init__(*args, **kwargs)

        self.product_pks = set([])
        for dp in products:
            str_pk = str(dp.pk)
            self.product_pks.add(str_pk)
            self.fields[str_pk] = forms.fields.BooleanField(required=False)

    def clean(self):
        if not any(self.cleaned_data.get(str_pk) for str_pk in self.product_pks):
            raise ValidationError('No data product selected')

    def get_selected_products(self):
        """
        Return the set of products that were selected
        """
        return {
            DataProduct.objects.get(pk=int(str_pk))
            for str_pk, checked in self.cleaned_data.items() if str_pk in self.product_pks and checked
        }


class DataProductActionForm(DataProductSelectionForm):
    """
    Form for selecting a group of data products from the target page to perform
    some action on them
    """
    action = forms.CharField(required=True)

    def __init__(self, *args, **kwargs):
        target = kwargs.pop('target')
        super().__init__(*args, **kwargs, products=target.dataproduct_set.all())


class GalleryForm(DataProductSelectionForm):
    """
    Form for a user to add a selection of data products to a data product group
    """
    group = forms.ModelChoiceField(DataProductGroup.objects.all())
