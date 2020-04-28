from tom_dataproducts.templatetags import dataproduct_extras


@dataproduct_extras.register.inclusion_tag('tom_dataproducts/partials/dataproduct_list_for_target.html',
                                           takes_context=True)
def dataproduct_list_for_target(context, target):
    """
    Override the product list for a target so that included template receives
    the whole current context
    """
    target_ctx = dataproduct_extras.dataproduct_list_for_target(target=target, context=context)
    context.update(target_ctx)
    return context
