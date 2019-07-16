import sys

from django.conf import settings

import tom_education.models as education_models
from tom_education.models import (
    AsyncError, TimelapseDataProduct, TimelapseProcess, ASYNC_STATUS_FAILED,
    PipelineProcess
)

def task(func, **kwargs):
    """
    Decorator that wraps dramatiq.actor, but does not import dramatiq if
    django_dramatiq is not in use
    """
    if 'test' not in sys.argv and 'django_dramatiq' in settings.INSTALLED_APPS:
        import dramatiq
        return dramatiq.actor(func, **kwargs)

    func.send = func
    return func

@task
def make_timelapse(tl_prod_pk):
    """
    Task to create the timelapse for the given TimelapseDataProduct
    """
    try:
        tl_prod = TimelapseDataProduct.objects.get(pk=tl_prod_pk)
    except TimelapseDataProduct.DoesNotExist:
        print('warning: could not find TimelapseDataProduct with PK {}'.format(tl_prod_pk),
              file=sys.stderr)
        return

    process = TimelapseProcess.objects.create(
        identifier=tl_prod.get_filename(), timelapse_product=tl_prod, target=tl_prod.target
    )
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
