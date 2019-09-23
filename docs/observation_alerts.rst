Observation alerts
==================

An *observation alert* is a combination of an email address and an observation
record. Alerts can be created through the
:ref:`API <observation-alert-api>`.

To process alerts and send email updates, a management command
``process_observation_alerts`` is available: ::

    $ ./manage.py process_observation_alerts

This will:

* Update the status of all observations associated with an alert
* Download new data, if available
* Create a :doc:`timelapse <timelapses>` for each target with new data, and
  delete old timelapses
* Send an email for each alert whose observation had new data

Email setup
-----------

To configure sending emails:

* Set the ``TOM_EDUCATION_FROM_EMAIL_ADDRESS`` setting in ``settings.py`` to the
  email address to use for the 'From:' header.
* Set ``EMAIL_HOST`` and ``EMAIL_PORT`` to the host and port of your SMTP server.

See the `django email documentation
<https://docs.djangoproject.com/en/2.2/topics/email/>`_ for more detail.

During development and testing, it is convenient to use the 'console' email
backend, which prints would-be emails to stdout instead of actually sending
them. Set ``EMAIL_BACKEND`` in ``settings.py`` as follows: ::

    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
