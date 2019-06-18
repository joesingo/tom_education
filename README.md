# tom_education

Plugin for the TOM Toolkit, adding the following features.

* **Templated observation forms:** when creating a new observation, the form
  fields can be saved as a template. Future observations can then be created
  from the template with all fields identical except for 'group ID', which has
  the date appended to it.

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

4. Set `ROOT_URLCONF` in `settings.py` to `mytom.urls`, where `mytom` is the
   name of the project created in step 1.

5. Set `TOM_FACILITY_CLASSES` in `settings.py`:

```
TOM_FACILITY_CLASSES = [
    'tom_observations.facilities.lco.LCOFacility',
]
```

6. Include `tom_education` and `tom_common` in `urls.py`:

```python
from django.urls import path, include

urlpatterns = [
    ...
    path('', include('tom_education.urls')),
    path('', include('tom_common.urls')),
]
```

7. Run migrations:

```
python manage.py migrate
```
