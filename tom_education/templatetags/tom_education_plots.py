from plotly import offline
import plotly.graph_objs as go
from django import template
import json
from astropy.time import Time

from tom_observations.models import ObservationRecord
from tom_dataproducts.models import ReducedDatum

register = template.Library()


@register.inclusion_tag('tom_targets/partials/target_photometry.html')
def targets_reduceddata(targetid):
    # order targets by creation date
    records = ObservationRecord.objects.filter(target__id=targetid)
    buttons = []
    data = []
    for n, record in enumerate(records):
        datasource = ReducedDatum.objects.filter(data_product__observation_record=record)
        if datasource.count() == 0:
            continue
        # x axis: target names. y axis: datum count
        x = []
        y = []
        err = []
        menu_bool = [False]*records.count()
        menu_bool[n] = True
        for rd in datasource:
            try:
                pdata = json.loads(rd.value)
            except json.JSONDecodeError:
                continue
            x.append(rd.timestamp.isoformat())
            y.append(pdata['magnitude'])
            err.append(pdata['error'])
        data.append(go.Scatter(x=x, y=y, error_y=dict(
            type='data', array=err), mode='markers'))
        button = dict(label=f"{record.scheduled_start.isoformat()[0:19]}",
             method="update",
             args=[{"visible": menu_bool},
                   {"title": f"Observations on {record.scheduled_start.isoformat()[0:19]}",
                    "annotations": []}]
            )
        buttons.append(button)
    if not data:
        return {'figure' : None}
    # Create the plot
    fig = go.Figure(data=data)
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
    updatemenus=[{'active' : 0,
                    'buttons' : buttons,
                    'showactive': True,
                    'x' : 0.1,
                    'xanchor' : "left",
                    'y' : 1.15,
                    'yanchor' : "top"}])

    figure = offline.plot(fig, output_type='div', show_link=False)
    # Add plot to the template context
    return {'figure': figure}
