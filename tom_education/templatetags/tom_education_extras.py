from django import template

register = template.Library()

@register.inclusion_tag('tom_education/dataproduct_checkbox.html')
def dataproduct_checkbox(product):
    is_reduced = not product.data.name.endswith('e00.fits.fz')
    return {'product': product, 'reduced': is_reduced}

@register.simple_tag
def loading_message():
    return 'Loading...'
