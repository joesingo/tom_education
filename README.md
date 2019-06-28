# tom_education

Plugin for the TOM Toolkit, adding the following features.

## Templated observation forms

When creating a new observation, the form fields can be saved as a template.
Future observations can then be created from the template with all fields
identical except for 'group ID', which has the date appended to it.

## Timelapses

On the detailed view for a target, a timelapse of FITS data products can be
created as animated GIFs or MP4 or WebM video. Options can be configured with
`TOM_EDUCATION_TIMELAPSE_SETTINGS` in `settings.py`, e.g.

```python
TOM_EDUCATION_TIMELAPSE_SETTINGS = {
    'format': 'webm',
    'fps': 15
}
```

The creation of timelapses is asynchronous to avoid long page-load times. This
can optionally be done by separate worker processes in a queue using
[Dramatiq](https://dramatiq.io/) via
[django_dramatiq](https://github.com/Bogdanp/django_dramatiq) and
[Redis](https://redis.io/) or [RabbitMQ](https://www.rabbitmq.com/). See the
instructions below for setting up Dramatiq with `tom_education`.

**TODO:** document how to start Dramatiq workers

## Installation

1. Set up a TOM following the [getting started guide](https://tomtoolkit.github.io/docs/getting_started).

2. Clone and install this package with `pip`:

```
git clone <this repo>
pip install tom_education
```

3. Add `tom_education` to `INSTALLED_APPS` in `settings.py` (make sure it
  appears *before* the other `tom_*` apps):

```python
INSTALLED_APPS = [
    ...
    'tom_education',
    'tom_targets',
    'tom_alerts',
    'tom_catalogs',
    'tom_observations',
    'tom_dataproducts',
]
```

If using Dramatiq for timelapses, add `django_dramatiq` here too.

4. Set `ROOT_URLCONF` in `settings.py` to `mytom.urls`, where `mytom` is the
   name of the project created in step 1.

5. Set `TOM_FACILITY_CLASSES` in `settings.py`:

```
TOM_FACILITY_CLASSES = [
    'tom_observations.facilities.lco.LCOFacility',
]
```

6. If using Dramatiq, configure the message broker in `settings.py`. E.g. to
   use Redis running on `localhost:6379`, but not in tests, use:

```python
import sys
testing = ('test' in sys.argv)
DRAMATIQ_BROKER = {
    'BROKER': 'dramatiq.brokers.redis.RedisBroker' if not testing else 'dramatiq.brokers.stub.StubBroker',
    'OPTIONS': {'url': 'redis://localhost:6379'} if not testing else {},
    'MIDDLEWARE': [
        'dramatiq.middleware.AgeLimit',
        'dramatiq.middleware.TimeLimit',
        'dramatiq.middleware.Callbacks'
```

7. Include `tom_education` and `tom_common` in `urls.py`:

```python
from django.urls import path, include

urlpatterns = [
    ...
    path('', include('tom_education.urls')),
    path('', include('tom_common.urls')),
]
```

8. Run migrations:

```
python manage.py migrate
```
