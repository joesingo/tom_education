from tom_dataproducts.templatetags import dataproduct_extras
from tom_dataproducts.models import ReducedDatum

from tom_education.models import TimelapseProcess, ASYNC_STATUS_CREATED


def exclude_non_created_timelapses(products):
    """
    Filter the given iterable of DataProducts to remove timelapses that are
    associated with an unfinished async process
    """
    for prod in products:
        qs = TimelapseProcess.objects.filter(timelapse_product=prod).exclude(status=ASYNC_STATUS_CREATED)
        if not qs.exists():
            yield prod


@dataproduct_extras.register.inclusion_tag('tom_dataproducts/partials/dataproduct_list_for_target.html',
                                           takes_context=True)
def dataproduct_list_for_target(context, target):
    """
    Override to product list for a target to exclude timelapses that are not in
    the created state, and also to that included template receives the whole
    current context
    """
    target_ctx = dataproduct_extras.dataproduct_list_for_target(target)
    target_ctx['products'] = list(exclude_non_created_timelapses(target_ctx['products']))
    context.update(target_ctx)
    return context
