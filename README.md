# tom_education

 [![Build Status](https://travis-ci.org/joesingo/tom_education.svg?branch=master)](https://travis-ci.org/joesingo/tom_education)
[![Documentation Status](https://readthedocs.org/projects/tom-education/badge/?version=latest)](https://tom-education.readthedocs.io/en/latest/?badge=latest)

TOM Education is a plugin for the TOM Toolkit adding features intended for
educational use. [See the
documentation](https://tom-education.readthedocs.io/en/latest/) for more
information.

## Features

* [Templated observation
  forms](https://tom-education.readthedocs.io/en/latest/templated_observation_forms.html):
  Save the fields in the observation creation form as a template to make it
  easier to create multiple observations with similar parameters.

* [Timelapses](https://tom-education.readthedocs.io/en/latest/timelapses.html):
  Create a timelapse of FITS data products for a target. Timelapses can be
  created as animated GIFs or MP4 or WebM videos.

* [Data gallery](https://tom-education.readthedocs.io/en/latest/gallery.html):
  View a gallery of thumbnails of FITS files which allows files to be selected
  and added to a data product group.

* [Data pipelines](https://tom-education.readthedocs.io/en/latest/pipelines.html):
  Run a user-supplied data pipeline on a selection of files and save the
  outputs as data products in the TOM.

* [API endpoints](https://tom-education.readthedocs.io/en/latest/apis.html):
  REST API endpoints give information about targets, timelapses, pipeline runs,
  and allow observations to be submitted.

* [Observation alerts](https://tom-education.readthedocs.io/en/latest/observation_alerts.html):
   Associate an email address with an observation to receive email updates when
   data is available.

* [Observations with multiple instrument configurations](https://tom-education.readthedocs.io/en/latest/multiple_instrument_configs.html):
  Submit LCO observations with multiple filters and exposure settings.

Long-running tasks (such as running data pipelines and creating large
timelapses) are performed asynchronously in separate worker processes using
[Dramatiq](https://dramatiq.io/) via
[django_dramatiq](https://github.com/Bogdanp/django_dramatiq) and
[Redis](https://redis.io).

## Requirements

In addition to the requirements listed in `setup.py` you will need:

- A working TOM (see [TOM Toolkit](https://tomtoolkit.github.io/) documentation)
- Python >= 3.6

## Installation

1. Set up a TOM following the [getting started guide](https://tomtoolkit.github.io/docs/getting_started).

2. Clone and install this package with `pip`:

```
pip install tom_education
```

**Note:** a dependency of one of `tom_education`'s dependencies requires a
Fortran compiler to install. On Ubuntu, run `sudo apt-get install gfortran`
before installing with `pip`.

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

5. Install [Redis](https://redis.io), and start `redis-server`. If not running
  Redis on the same server as `tom_education`, or if using a non-default port,
  change the Redis connection settings in `settings.py` under
  `DRAMATIQ_BROKER`.

6. Start the Dramatiq worker processes:

```
python manage.py rundramatiq
```

Note that `rundramatiq` must be restarted for code changes to take effect.

7. Optional: install test dependencies and run tests to check everything is
okay (**Note**: Redis and the Dramatiq workers do not have to be running to run
the tests).

```
pip install tomtoolkit[test]
python manage.py test tom_education
```

### Install Development version

Clone this repo and install the package with `pip`:

```
git clone https://github.com/joesingo/tom_education
pip install -e tom_education
```
