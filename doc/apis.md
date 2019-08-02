# API endpoints

## Overview

Each API endpoint has the form `/api/*`, and returns a JSON response. For POST
requests, send data as JSON and set the `Content-Type` HTTP header to
`application/json`.

Any field representing a date and time is given as a [UNIX
timestamp](https://en.wikipedia.org/wiki/Unix_time) as returned by
[datetime.timestamp()](https://docs.python.org/3.9/library/datetime.html#datetime.datetime.timestamp)
in the Python standard library.

## Async process status API

Get information about all asynchronous processes (timelapses, pipelines etc)
associated with a given target.

**URL:** `/api/async/status/<target PK>/`

**Method:** GET

**Output:**

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

## Pipeline logs API

An extension of the async process API for pipeline processes.

**URL:** `/api/pipeline/logs/<pipeline PK>/

**Method:** GET

**Output:**

A single key-value object which contains all the fields in the `processes`
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
  "logs": "Processing test_dp_ftfn0m410-kb23-20190413-0059-e91.fits.fz\nProcessing test_dp_ftfn0m410-kb23-20190413-0057-e91.fits.fz...",
  "group_name": "dummy_m13_2019-07-22-163925_outputs",
  "group_url": "/dataproducts/data/group/37/"
}
```
