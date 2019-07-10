import sys

from django.conf import settings

from tom_education.models import AsyncError, TimelapseDataProduct, TimelapseProcess, ASYNC_STATUS_FAILED

def task(func, **kwargs):
    """
    Decorator that wraps dramatiq.actor, but does not import dramatiq if
    django_dramatiq is not in use
    """
    if 'django_dramatiq' in settings.INSTALLED_APPS:
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
