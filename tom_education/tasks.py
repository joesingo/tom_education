import dramatiq

from tom_education.models import TimelapseDataProduct


@dramatiq.actor
def make_timelapse(tl_prod_pk):
    """
    Task to create the timelapse for the given TimelapseDataProduct
    """
    # TODO: handle errors
    tl_prod = TimelapseDataProduct.objects.get(pk=tl_prod_pk)
    tl_prod.write()
