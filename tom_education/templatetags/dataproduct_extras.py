from django import template
from tom_dataproducts.templatetags import dataproduct_extras

from tom_education.models import TimelapseDataProduct, ASYNC_STATUS_CREATED


def exclude_non_created_timelapses(products):
    """
    Return a generator of DataProducts that are either not timelapses, or are
    in the 'created' state
    """
    for prod in products:
        try:
            timelapse_prod = TimelapseDataProduct.objects.get(pk=prod.pk)
        except TimelapseDataProduct.DoesNotExist:
            yield prod
            continue

        if timelapse_prod.status == ASYNC_STATUS_CREATED:
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
