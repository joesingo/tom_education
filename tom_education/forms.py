from django import forms
from django.core.exceptions import ValidationError
from crispy_forms.layout import Button, Layout, HTML
from tom_dataproducts.models import DataProduct, DataProductGroup

from tom_education.models import ObservationTemplate


class SecondarySubmit(Button):
    """
    Button that has the appearance of a regular button, but will submit a form.
    Used to differentiate between primary and secondary submit buttons
    """
    input_type = 'submit'


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
            self.instantiate_template_url = kwargs.pop('instantiate_template_url')
            show_create = kwargs.pop('show_create')

            super().__init__(*args, **kwargs)

            if show_create:
                self.helper.add_input(SecondarySubmit(*self.new_template_action))

            # Insert template links after common layout
            if self.helper.layout:
                self.helper.layout.insert(1, self.pre_layout())
            else:
                self.helper.layout = Layout(self.common_layout, self.pre_layout())

        def pre_layout(self):
            """
            Add links at top of form to instantiate fields from a template
            """
            templates = ObservationTemplate.objects.filter(
                target__pk=self.initial['target_id'],
                facility=self.initial['facility']
            )
            if templates:
                links = []
                for template in templates:
                    links.append('<a href="{url}">{text}</a>'.format(
                        url=template.get_create_url(self.instantiate_template_url),
                        text=template.name
                    ))
                return Layout(HTML('Create from template: '), HTML(', '.join(links)))
            return Layout()
    return F


class DataProductSelectionForm(forms.Form):
    """
    Base class for a form including a list of data product checkboxes, where
    the list of data products is taken from the 'products' kwarg to __init__
    """
    def __init__(self, *args, **kwargs):
        products = kwargs.pop('products')
        super().__init__(*args, **kwargs)

        self.product_ids = set([])
        for dp in products:
            self.product_ids.add(dp.product_id)
            self.fields[dp.product_id] = forms.fields.BooleanField(required=False)

    def clean(self):
        if not any(self.cleaned_data.get(pid) for pid in self.product_ids):
            raise ValidationError('No data product selected')

    def get_selected_products(self):
        """
        Return the set of products that were selected
        """
        return {
            DataProduct.objects.get(product_id=pid)
            for pid, checked in self.cleaned_data.items() if pid in self.product_ids and checked
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
