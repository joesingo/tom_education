import sys

from django.conf import settings
import dramatiq

import tom_education.models as education_models
from tom_education.models import (
    AsyncError, TimelapseProcess, ASYNC_STATUS_FAILED, PipelineProcess
)


def task(func, **kwargs):
    """
    Decorator that wraps dramatiq.actor, but runs tasks synchronously during
    tests
    """
    if 'test' not in sys.argv:
        return dramatiq.actor(func, **kwargs)
    func.send = func
    return func


@task
def make_timelapse(tl_process_pk):
    """
    Task to create the timelapse for the given TimelapseProcess
    """
    try:
        process = TimelapseProcess.objects.get(pk=tl_process_pk)
    except TimelapseProcess.DoesNotExist:
        print('warning: could not find TimelapseProcess with PK {}'.format(tl_process_pk),
              file=sys.stderr)
        return

    run_process(process)


@task
def run_pipeline(process_pk, cls_name):
    try:
        pipeline_cls = PipelineProcess.get_subclass(cls_name)
    except ImportError:
        print('warning: pipeline \'{}\' not found'.format(cls_name), file=sys.stderr)
        return
    try:
        process = pipeline_cls.objects.get(pk=process_pk)
    except pipeline_cls.DoesNotExist:
        print('warning: could not find {} with PK {}'.format(pipeline_cls.__name__, process_pk),
              file=sys.stderr)
        return
    run_process(process)


def run_process(process):
    print("running process")
    failure_message = None
    try:
        process.run()
    except AsyncError as ex:
        failure_message = str(ex)
    except Exception as ex:
        print('warning: unknown error occurred: {}'.format(ex))
        failure_message = 'An unexpected error occurred'

    if failure_message is not None:
        print('task failed: {}'.format(failure_message))
        process.failure_message = failure_message
        process.status = ASYNC_STATUS_FAILED
        process.save()
    print('process finished')
