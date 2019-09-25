import json

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from tom_dataproducts.models import DataProductGroup
from tom_targets.models import TargetExtra
from tom_observations.models import ObservationRecord

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
    EMOJI_CHOICES = {
        'PENDING': '🕒',
        'FAILED': '❌',
        'WINDOW_EXPIRED': '❌',
        'COMPLETED': '✅'
    }
    return format_html(mark_safe('<span title={}>{}</span>'.format(
        status, EMOJI_CHOICES.get(status, '😑')
    )))


@register.inclusion_tag('tom_targets/partials/target_features.html')
def featured_images(target):
    return {'target': target}


@register.inclusion_tag('tom_dataproducts/partials/dataproduct_thumbs_for_target.html')
def dataproduct_thumbs_for_target(target):
    return {
        'products': target.dataproduct_set.filter(data__contains='fits').order_by('-created')[:6],
        'target': target
    }


@register.inclusion_tag('tom_dataproducts/partials/dataproduct_other_for_target.html')
def dataproduct_other_for_target(target):
    timelapses = target.dataproduct_set.filter(tag='timelapse')
    return {
        'timelapse': timelapses.latest() if timelapses else None,
        'photometry': target.dataproduct_set.filter(tag='photometry'),
        'target': target
    }


@register.filter
def dataproduct_extrainfo(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


@register.inclusion_tag('tom_targets/partials/target_latest_active.html')
def target_latest_active():
    return {'targets': TargetExtra.objects.filter(key='active', value=True)}


@register.inclusion_tag('tom_observations/partials/observationrecord_latest.html')
def observationrecord_latest(value=10):
    value = int(value)
    return {'observationrecords': ObservationRecord.objects.all().order_by('-modified')[:value]}


@register.filter
def get_form_field(form, label):
    """
    Return a bound field with the given label from a form
    """
    return form.fields[label].get_bound_field(form, label)
