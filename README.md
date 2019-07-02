# tom_education

Plugin for the TOM Toolkit adding features intended for educational use.

## Installation

1. Set up a TOM following the [getting started guide](https://tomtoolkit.github.io/docs/getting_started).

2. Clone and install this package with `pip`:

```
git clone <this repo>
pip install tom_education
```

3. Add `tom_education` to `INSTALLED_APPS` in `settings.py`.

```python
INSTALLED_APPS = [
    ...
    'tom_education'
]
```

4. Run the `tom_education` setup management command. Note that this overwrites
   `settings.py` and `urls.py` in the newly created project.

```
python manage.py tom_education_setup
```

5. Optional: run tests to check everything is okay

```
python manage.py test tom_education
```

## Features

### Templated observation forms

When creating a new observation, the form fields can be saved as a template.
Future observations can then be created from the template with all fields
identical except for 'group ID', which has the date appended to it.

### Timelapses

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
[Redis](https://redis.io/) or [RabbitMQ](https://www.rabbitmq.com/).

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

#### Management Command

Timelapses can also be created through the management command `create_timelapses`.

```
./manage.py create_timelapse <target PK>
```

This will create a timelapse for all reduced data products associated with the
given target that are contained in the data product group 'Timelapse quality'.
This group name can be changed by setting `TOM_EDUCATION_TIMELAPSE_GROUP_NAME`
in `settings.py`.
