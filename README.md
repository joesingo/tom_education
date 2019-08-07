# tom_education

Plugin for the TOM Toolkit adding features intended for educational use.

## Features

* [Templated observation forms](doc/templated_observation_forms.md): Save the
  fields in the observation creation form as a template to make it easier to
  create multiple observations with similar parameters.

* [Timelapses](doc/timelapses.md): Create a timelapse of FITS data products for a
 target. Timelapses can be created as animated GIFs or MP4 or WebM videos.

* [Data gallery](doc/gallery.md): View a gallery of thumbnails of FITS files which
  allows files to be selected and added to a data product group.

* [Data pipelines](doc/pipelines.md): Run a user-supplied data pipeline on a
  selection of files and save the outputs as data products in the TOM.

* [API endpoints](doc/apis.md): REST API endpoints give information about
  targets, timelapses, pipeline runs, and allow observations to be submitted.

* [Observation alerts](doc/observation_alerts.md): Associate an email address
  with an observation to receive email updates when data is available

Long-running tasks (such as running data pipelines and creating large
timelapses) are performed asynchronously in separate worker processes using
[Dramatiq](https://dramatiq.io/) via
[django_dramatiq](https://github.com/Bogdanp/django_dramatiq) and
[Redis](https://redis.io).

## Installation

**Note:** At the time of writing, `tom_education` uses features of `tomtoolkit`
that are not yet released. After installation, uninstall `tomtoolkit` and
install the `development` branch [from
GitHub](https://github.com/TOMToolkit/tom_base).

1. Set up a TOM following the [getting started guide](https://tomtoolkit.github.io/docs/getting_started).

2. Clone and install this package with `pip`:

```
git clone <this repo>
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
