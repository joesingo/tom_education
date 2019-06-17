# tom_education

Plugin for the TOM Toolkit.

## Installation

1. Set up a TOM following the [getting started guide](https://tomtoolkit.github.io/docs/getting_started).

2. Clone and install this package with `pip`

```
git clone <this repo>
pip install tom_education
```

3. Add `tom_education` to `INSTALLED_APPS` in `settings.py`

4. Set `ROOT_URLCONF` in `settings.py` to `mytom.urls`, where `mytom` is the
   name of the project created in step 1.

5. Include `tom_education` and `tom_common` in `urls.py`

```python
from django.urls import path, include

urlpatterns = [
    ...
    path('', include('tom_education.urls')),
    path('', include('tom_common.urls')),
]
```

6. Run migrations

```
python manage.py migrate
```
