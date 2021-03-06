TOM Education
=============

.. image:: https://travis-ci.org/joesingo/tom_education.svg?branch=master
   :target: https://travis-ci.org/joesingo/tom_education

TOM Education is a plugin for the `TOM Toolkit
<https://lco.global/tomtoolkit/>`_ adding features intended for educational
use.

Features
--------

* :doc:`templated_observation_forms`: Save the fields in the observation
  creation form as a template to make it easier to create multiple observations
  with similar parameters.

* :doc:`timelapses`: Create a timelapse of FITS data products for a target.
  Timelapses can be created as animated GIFs or MP4 or WebM videos.

* :doc:`gallery`: View a gallery of thumbnails of FITS files which allows files
  to be selected and added to a data product group.

* :doc:`pipelines`: Run a user-supplied data pipeline on a selection of files
  and save the outputs as data products in the TOM.

* :doc:`apis`: REST API endpoints give information about targets, timelapses,
  pipeline runs, and allow observations to be submitted.

* :doc:`observation_alerts`: Associate an email address with an observation to
  receive email updates when data is available.

* :doc:`multiple_instrument_configs`: Submit LCO observations with multiple
  filters and exposure settings.

Long-running tasks (such as running data pipelines and creating large
timelapses) are performed asynchronously in separate worker processes using
`Dramatiq <https://dramatiq.io/>`_ via `django_dramatiq
<https://github.com/Bogdanp/django_dramatiq>`_ and `Redis <https://redis.io>`_.

Requirements
------------

In addition to the requirements listed in ``setup.py`` you will need:

- A working TOM (see the `TOM Toolkit documentation <https://tomtoolkit.github.io/>`_)
- Python >= 3.6

Installation
------------

1. Set up a TOM following the `getting started guide
   <https://tomtoolkit.github.io/docs/getting_started>`_.

2. Clone and install this package with ``pip``: ::

    pip install tom_education

**Note:** a dependency of one of ``tom_education``'s dependencies requires a
Fortran compiler to install. On Ubuntu, run ``sudo apt-get install gfortran``
before installing with ``pip``.

3. Add ``tom_education`` to ``INSTALLED_APPS`` in ``settings.py``: ::

    INSTALLED_APPS = [
        ...
        'tom_education'
    ]

4. Run the ``tom_education`` setup management command. Note that this
   overwrites ``settings.py`` and ``urls.py`` in the newly created project. ::

    python manage.py tom_education_setup

5. Install `Redis <https://redis.io>`_, and start ``redis-server``. If not
   running Redis on the same server as ``tom_education``, or if using a
   non-default port, change the Redis connection settings in ``settings.py``
   under ``DRAMATIQ_BROKER``.

6. Start the Dramatiq worker processes: ::

    python manage.py rundramatiq

Note that ``rundramatiq`` must be restarted for code changes to take effect.

7. Optional: install test dependencies and run tests to check everything is
okay (**Note**: Redis and the Dramatiq workers do not have to be running to run
the tests) ::

    pip install tomtoolkit[test]
    python manage.py test tom_education

Install Development version
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Clone this repo and install the package with ``pip``: ::

    git clone https://github.com/joesingo/tom_education
    pip install -e tom_education

Documentation
-------------

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   templated_observation_forms
   timelapses
   gallery
   pipelines
   apis
   observation_alerts
   Observations with multiple filters <multiple_instrument_configs>
