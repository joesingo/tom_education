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

@dataproduct_extras.register.inclusion_tag('tom_dataproducts/partials/astrosource_for_target.html')
def astrosource_for_target(target):
    photometry_data = {}
    for datum in ReducedDatum.objects.filter(target=target, data_type=PHOTOMETRY[0]):
        values = json.loads(datum.value)
        photometry_data.setdefault(values['filter'], {})
        photometry_data[values['filter']].setdefault('time', []).append(datum.timestamp)
        photometry_data[values['filter']].setdefault('magnitude', []).append(values.get('magnitude'))
        photometry_data[values['filter']].setdefault('error', []).append(values.get('error'))
    plot_data = [
        go.Scatter(
            x=filter_values['time'],
            y=filter_values['magnitude'], mode='markers',
            name=filter_name,
            error_y=dict(
                type='data',
                array=filter_values['error'],
                visible=True
            )
        ) for filter_name, filter_values in photometry_data.items()]
    layout = go.Layout(
        yaxis=dict(autorange='reversed'),
        height=600,
        width=700
    )
    return {
        'target': target,
        'plot': offline.plot(go.Figure(data=plot_data, layout=layout), output_type='div', show_link=False)
    }
