import sys

from django.conf import settings

from tom_education.models import TimelapseDataProduct, DateFieldNotFoundError, TIMELAPSE_FAILED

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

    failure_message = None
    try:
        tl_prod.write()
    except DateFieldNotFoundError as ex:
        failure_message = str(ex)
    except ValueError as ex:
        print('warning: ValueError: {}'.format(ex))
        failure_message = 'Invalid parameters. Are all images the same size?'
    except Exception as ex:
        print('warning: unknown error occurred: {}'.format(ex))
        failure_message = 'An unexpected error occurred'

    if failure_message is not None:
        print('task failed: {}'.format(failure_message))
        tl_prod.failure_message = failure_message
        tl_prod.status = TIMELAPSE_FAILED

    tl_prod.save()
