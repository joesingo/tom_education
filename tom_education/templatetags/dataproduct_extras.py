from django import template
from tom_dataproducts.templatetags import dataproduct_extras

from tom_education.models import TimelapseDataProduct, TimelapseProcess, ASYNC_STATUS_CREATED


def exclude_non_created_timelapses(products):
    """
    Filter the given iterable of DataProducts to remove timelapses that are
    associated with an unfinished async process
    """
    for prod in products:
        qs = TimelapseProcess.objects.filter(timelapse_product=prod).exclude(status=ASYNC_STATUS_CREATED)
        if not qs.exists():
            yield prod


@dataproduct_extras.register.inclusion_tag('tom_dataproducts/partials/dataproduct_list_for_target.html')
def dataproduct_list_for_target(target):
    """
    Override to product list for a target to exclude timelapses that are not in
    the created state
    """
    context = dataproduct_extras.dataproduct_list_for_target(target)
    context['products'] = list(exclude_non_created_timelapses(context['products']))
    return context
