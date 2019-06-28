from django.conf import settings

from tom_education.models import TimelapseDataProduct

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
    # TODO: handle errors
    tl_prod = TimelapseDataProduct.objects.get(pk=tl_prod_pk)
    tl_prod.write()
