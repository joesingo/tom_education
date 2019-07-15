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
