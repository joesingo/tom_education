from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from tom_dataproducts.models import DataProductGroup

from tom_education.constants import RAW_FILE_EXTENSION

register = template.Library()

@register.inclusion_tag('tom_education/dataproduct_checkbox.html')
def dataproduct_checkbox(product):
    is_reduced = 'fits' in product.data.name and not product.data.name.endswith(RAW_FILE_EXTENSION)
    return {
        'product': product,
        'reduced': is_reduced,
        'groups': product.group.all(),
    }

@register.inclusion_tag('tom_education/dataproduct_selection_buttons.html', takes_context=True)
def dataproduct_selection_buttons(context, show_group_selection=True):
    context['show_group_selection'] = show_group_selection
    if show_group_selection:
        target = context['target']
        context['data_product_groups'] = DataProductGroup.objects.filter(dataproduct__target=target).distinct()
    return context

@register.simple_tag
def loading_message():
    return 'Loading...'


@register.simple_tag
def status_icon(status):
    EMOJI_CHOICES = {'PENDING' : '🕒',
              'FAILED' : '❌',
              'WINDOW_EXPIRED' : '❌',
              'COMPLETED' : '✅'}
    return format_html(mark_safe('<span title={}>{}</span>'.format(status, EMOJI_CHOICES.get(status,'😑'))))

@register.inclusion_tag('tom_targets/partials/target_features.html')
def featured_images(target):
    return {'target': target}
