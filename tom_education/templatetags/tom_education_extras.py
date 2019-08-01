from django import template

from tom_education.constants import RAW_FILE_EXTENSION

register = template.Library()

@register.inclusion_tag('tom_education/dataproduct_checkbox.html')
def dataproduct_checkbox(product):
    is_reduced = not product.data.name.endswith(RAW_FILE_EXTENSION)
    return {'product': product, 'reduced': is_reduced}

@register.simple_tag
def loading_message():
    return 'Loading...'
