# Timelapses

On the detailed view for a target under 'Manage Data', a timelapse of FITS data
products can be created as animated GIFs or MP4 or WebM video.

Options can be configured with `TOM_EDUCATION_TIMELAPSE_SETTINGS` in
`settings.py`, e.g.

```python
TOM_EDUCATION_TIMELAPSE_SETTINGS = {
    'format': 'webm',
    'fps': 15
}
```

The creation of timelapses can optionally be performed asynchronously in
separate worker processes in a queue using [Dramatiq](https://dramatiq.io/) via
[django_dramatiq](https://github.com/Bogdanp/django_dramatiq) and
[Redis](https://redis.io/) or [RabbitMQ](https://www.rabbitmq.com/) in order to
avoid long page-load times.

To do so, uncomment the `django_dramatiq` line from `INSTALLED_APPS` in
`settings.py`, and install the dependencies:

```
pip install django_dramatiq
pip install redis  # if using Redis
```

To start the worker processes, using the `rundramatiq` management command from
`django_dramatiq`:

```
python manage.py rundramatiq
```

(If this fails with an error message regarding `--watch`, try `pip install
watchdog_gevent` first).

Note that `rundramatiq` must be restarted each time the code is changed in
order for the changes to take effect.

## Management Command

Timelapses can also be created through the management command `create_timelapses`.

```
./manage.py create_timelapse <target PK>
```

This will create a timelapse for all reduced data products associated with the
given target that are contained in the data product group 'Good quality data'.
This group name can be changed by setting `TOM_EDUCATION_TIMELAPSE_GROUP_NAME`
in `settings.py`.
