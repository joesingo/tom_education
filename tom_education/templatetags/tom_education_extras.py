from django import template

register = template.Library()

@register.inclusion_tag('tom_education/dataproduct_checkbox.html')
def dataproduct_checkbox(product):
    is_reduced = 'e91.fits.fz' not in product.data.name
    return {'product': product, 'reduced': is_reduced}
