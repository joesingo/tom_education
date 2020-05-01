from plotly import offline
import plotly.graph_objs as go
from django import template
import json
from astropy.time import Time

from tom_targets.models import Target

register = template.Library()


@register.inclusion_tag('tom_targets/partials/target_photometry.html')
def targets_reduceddata(targetid):
    # order targets by creation date
    target = Target.objects.get(id=targetid)
    # x axis: target names. y axis: datum count
    x = []
    y = []
    for rd in target.reduceddatum_set.all():
        try:
            data = json.loads(rd.value)
        except json.JSONDecodeError:
            continue
        print(rd.timestamp.isoformat())
        # t = Time(rd.timestamp.isoformat(), format='isot', scale='utc')
        x.append(rd.timestamp.isoformat())
        y.append(data['magnitude'])
    data = [go.Scatter(x=x, y=y, mode='markers')]
    # Create the plot
    fig = go.Figure(data=data)
    fig.update_yaxes(autorange="reversed")
    figure = offline.plot(fig, output_type='div', show_link=False)
    # Add plot to the template context
    return {'figure': figure}
