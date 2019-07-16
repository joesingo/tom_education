# Data Pipelines

In this project, a *pipeline* refers to a process that takes a `Target` and a
list of `DataProduct` objects as inputs, performs some process on the data
(which are usually FITS files), and produces some outputs. A *process* refers
to an instance of a pipeline for a particular target and set of input files.

Processes are run by selecting a number of data products on the target page in
the TOM, and selecting the pipeline to run. Processes run asynchronously, and a
separate page shown the status and log output as it progresses.

On completion, a new `DataProductGroup` is created to store the outputs of the
process as `DataProduct` objects.

**TODO:** provide some reference for the `tom_base` classes.

## Defining a pipeline

Pipelines are defined by creating a sub-class of
`tom_education.models.PipelineProcess` somewhere within your project, and
referencing them from `settings.py`, e.g:

```python
...
TOM_EDUCATION_PIPELINES = {
    # name: pipeline class. The name will be shown in the UI
    'My pipeline': 'my_project.pipelines.MyPipeline'
}
...
```

The following class serves as a minimal example showing the methods that must
be defined.

```python
class ExamplePipelineProcess(PipelineProcess):
    # Label used as a prefix for names of generated data products
    short_name = 'example'

    # Make this a proxy: we do not want this to be a concrete model (which
    # would use a separate DB table and require migrations)
    class Meta:
        proxy = True

    def do_pipeline(self, tmpdir):
        """
        This method does the actual work.

        `tmpdir` is `pathlib.Path` object for a temporary directory which can
        be used to write outputs and other temporary files.

        This method will return a sequence of Path objects for the output files
        that should be saved as new `DataProduct` objects in TOM.
        """
        # The `Target` object is available as `self.target`
        ra = self.target.ra
        dec = self.target.dec

        # The input files are available as `self.input_files`. This is a Django
        # `ManyRelatedManager` object of `DataProduct` objects: use
        # `self.input_files.all()` to get the inputs as a list.
        for product in self.input_files.all():
            path = product.data.path
            # Do something with file...

        # Create an output file
        outcsv = tmpdir / 'my_output.csv'
        outcsv.write_text('data here')

        return [outcsv]
```

## Errors

To stop a process and mark it as a failure, raise a `tom_education.models.AsyncError` exception:

```python
from tom_education.models import AsyncError
...

class MyPipeline(PipelineProcess):
    ...
    def do_pipeline(self, tmpdir):
        raise AsyncError('Something went terribly wrong')
```

This will set the `status` field of the process to
`tom_education.models.ASYNC_STATUS_FAILED`, and the given error message will be
shown in the UI.

## Status updates

For long-running pipelines, or ones with several steps, it may be useful to set
the status of a process as it progresses. For this, a `PipelineProcess` has a
`status` field which can be set to any string value. The `PipelineProcess` must
be saved after the status is changed with `self.save()`. This status will be
shown and updated in the UI on the page for the process.

To prevent repetition in the code when updating the status, performing some
task and saving, a context manager `self.update_status` is available:

```python
def do_pipeline(self, tmpdir):
    with self.update_status('Doing the first thing'):
        # do something
        ...

    with self.update_status('Done that - now doing the second thing')
        # do something else
        ...
    ...
```

On successful completion of the process (that is, if `do_pipeline()` finishes
without raising a `AsyncError`), the status is set to
`tom_education.models.ASYNC_STATUS_CREATED`.

## Log output

More granular updates can be given by logging messages with `self.log()`:

```python
def do_pipeline(self, tmpdir):
    with self.update_status('Doing something important'):
        self.log('first sub-step')
        self.log('second sub-step')
        ...
    ...
```

Log output is also shown in the UI on the page for a process.
