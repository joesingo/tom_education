# API endpoints

Each API endpoint has the form `/api/*`, and returns a JSON response. For POST
requests, send data as JSON and set the `Content-Type` HTTP header to
`application/json`.

Any field representing a date and time is given as a [UNIX
timestamp](https://en.wikipedia.org/wiki/Unix_time) as returned by
[datetime.timestamp()](https://docs.python.org/3.9/library/datetime.html#datetime.datetime.timestamp)
in the Python standard library.

The output formats described below are for success cases. If an error occurs,
the JSON response is of the form `{"detail": "<error message>"}` unless stated
otherwise.

The API endpoints are:

* [Async process API](#async-process-api): Get information about all
  asynchronous processes (timelapses, pipelines etc) associated with a given
  target.

* [Pipeline process API](#pipeline-process-api): An extension of the async
  process API for [pipeline processes](/doc/pipelines.md).

* [Target detail and timelapses API](#target-detail-and-timelapses-api):
  Return a subset of fields for a `Target` object and a listing of its
  associated timelapses.

* [Create observation alert API](#create-observation-alert-api): Create an
  observation and [observation alert](/doc/observation_alerts.md) by
  instantiating an [observation template](/doc/templated_observation_forms.md)
  for a target.

## Async process API

**URL:** `/api/async/status/<target PK>/`

**Method:** GET

**Output:** Key-value object with the following keys:

* `processes`: list of processes, sorted by creation time (most recent first).
  Each process has the following keys:
    * `identifier`
    * `created`: creation time
    * `status`: string field indicating the status of the process: the possible
      values depend on the type of process
    * `terminal_timestamp`: time at which the process finished or failed, or
      `null`
    * `failure_message`: message explaining why the process failed, or `null`
    * `view_url`: relative URL to info page if this is a pipeline processes, or
      `null` for other process types
* `timestamp`: current server time. This is useful for web clients that poll the
  API to detect when a process finishes, since the first received `timestamp`
  can be compared with the process's `terminal_timestamp` to exclude processes
  that were already finished at the time of page load.

**Example output:**
```
{
  "timestamp": 1564740590.527199,
  "processes": [
    {
      "identifier": "timelapse_m13_2019-08-02-100944.webm",
      "created": 1564740586.489885,
      "status": "created",
      "terminal_timestamp": 1564740590.162959,
      "failure_message": null,
      "view_url": null
    },
    {
      "identifier": "astrosource_m13_2019-07-30-122657",
      "created": 1564489617.601547,
      "status": "pending",
      "terminal_timestamp": null,
      "failure_message": null,
      "view_url": "/pipeline/51"
    }
  ]
}
```

## Pipeline process API

**URL:** `/api/pipeline/logs/<pipeline PK>/`

**Method:** GET

**Output:** A single key-value object which contains all the fields in the `processes`
objects from the async process API and the following additional fields:

* `logs`: log output from the pipeline process (see the [pipeline documentation
  on logging](/doc/pipelines.md#log-output))
* `group_name`: the name of the `DataProductGroup` which stores the outputs of
  this pipeline process, or `null` if the group has not yet been created.
* `group_url`: relative URL to the info page for the associated
  `DataProductGroup`, or `null` if the group has not yet been created.

**Example output:**
```
{
  "identifier": "dummy_m13_2019-07-22-163925",
  "created": 1563813565.83185,
  "status": "created",
  "terminal_timestamp": 1563813673.560319,
  "failure_message": null,
  "view_url": "/pipeline/45",
  "logs": "Processing test_dp_ftfn0m410-kb23-20190413-0059-e91.fits.fz",
  "group_name": "dummy_m13_2019-07-22-163925_outputs",
  "group_url": "/dataproducts/data/group/37/"
}
```

## Target detail and timelapses API

**URL:** `/api/target/<target PK>/`

**Method:** GET

**Output:** Key-value object with the following keys:

* `target`: key-value object:
    * `identifier`
    * `name`
    * `name2`
    * `name3`
    * `extra_fields`: key-value object containing [extra target
      fields](https://tomtoolkit.github.io/docs/target_fields)
* `timelapses`: list of timelapses sorted by creation time (most recent first).
  Each timelapse object has the following keys:
    * `name`: basename of timelapse filename
    * `format`: the format of the timelapse (e.g. `gif`)
    * `url`: URL from which the timelapses can be downloaded
    * `created`: creation time
    * `frames`: the number of frames that comprise the timelapse

**Example output:**
```
{
  "target": {
    "identifier": "m13",
    "name": "Hercules Globular Cluster",
    "name2": "",
    "name3": "",
    "extra_fields": {
      "mykey": "myvalue"
    }
  },
  "timelapses": [
    {
      "name": "timelapse_m13_2019-08-02-100915.webm",
      "format": "webm",
      "url": "/data/m13/none/timelapse_m13_2019-08-02-100915.webm",
      "created": 1564740555.119924,
      "frames": 2
    },
    {
      "name": "timelapse_m13_2019-08-02-093131.webm",
      "format": "webm",
      "url": "/data/m13/none/timelapse_m13_2019-08-02-093131.webm",
      "created": 1564738291.45856,
      "frames": 3
    }
  ]
}
```

## Create observation alert API

**URL:** `/api/observe/`

**Method:** POST

**Input**: A key-value JSON object with the following keys:

* `target`: primary key for the target object
* `template_name`: the name of the observation template to use
* `facility`: observing facility: currently only `LCO` is supported
* `overrides`: key-value mapping for form fields to override after populating
  fields through the observation template
* `email`: email address to associate with the observation alert

**Output:** The input JSON data is returned as output on success. If the input
is invalid, the response is of the form `{"<field_name>": ["<error message", ...],
...}` with error message(s) for each invalid field, or `{"detail": "<error
message>"}` for non-field errors.

**Example input:**
```
{
  "target": 1,
  "template_name": "my-template",
  "facility": "LCO",
  "overrides": {
    "start": "2019-08-05T00:00:00",
    "end": "2019-08-10T00:00:00"
  },
  "email": "someone@someplace.net"
}
```

### Rate throttling

This endpoint uses [Django REST Framework's
throttling](https://www.django-rest-framework.org/api-guide/throttling/) to
prevent abuse by limiting the number of observation alerts that can be created
per minute. This is controlled by the `REST_FRAMEWORK` setting, which is set as
follows by the setup script:
```
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'observe': '6/minute',
    },
}
```
The `observe` key can be changes to alter the throttling rate.
