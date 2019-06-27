import dramatiq

from tom_education.models import TimelapseDataProduct, TIMELAPSE_CREATED
from tom_education.timelapse import Timelapse


@dramatiq.actor
def make_timelapse(tl_prod_pk, filename, fmt, fps):
    """
    Task to create a timelapse and write it to a TimelapseDataProduct

    tl_prod_pk: PK for the TimelapseDataProduct to create the timelapse for
    filename:   Filename to write the timelapse file to
    fmt:        timelapse format
    fps:        frames per second
    """
    # TODO: handle errors
    tl_prod = TimelapseDataProduct.objects.get(pk=tl_prod_pk)
    product_pks = {prod.pk for prod in tl_prod.frames.all()}
    tl = Timelapse(product_pks, fmt, fps)  # TODO: handle DateFieldNotFoundError
    tl.write(tl_prod, filename)
    tl_prod.status = TIMELAPSE_CREATED
    tl_prod.save()
