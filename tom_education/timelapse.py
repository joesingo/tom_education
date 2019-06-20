from datetime import datetime
from io import BytesIO
import os.path
import tempfile

from astropy.io import fits
from django.core.files import File
from fits2image.conversions import fits_to_jpg
import imageio
from tom_dataproducts.models import DataProduct, IMAGE_FILE


class Timelapse:
    """
    Class to create an animated timelapse from a sequence of FITS image files
    """
    fits_date_field = 'DATE-OBS'

    def __init__(self, products, fmt='gif', fps=10):
        self.products = Timelapse.sort_products(products)
        if not self.products:
            raise ValueError("Empty data products list")
        self.format = fmt
        self.fps = fps

        # Check that all products have a common observation record and target
        obs_records = {prod.observation_record for prod in self.products}
        targets = {prod.target for prod in self.products}
        if len(obs_records) > 1 or len(targets) > 1:
            raise ValueError(
                'Cannot create a timelapse for data products from different '
                'observations or targets'
            )
        self.target = list(targets)[0]
        self.obs = list(obs_records)[0]

    def create(self, outfile):
        """
        Create the timelapse output file. `outfile` may be a path or file-like
        object
        """
        # Open the first file to get image size; we assume all images are the
        # same size. The size is required for fits2image, which defaults to
        # 200x200 instead of preserving original size...
        size = None
        for hdu in fits.open(self.products[0].data.path):
            try:
                size = (hdu.header['NAXIS1'], hdu.header['NAXIS2'])
            except KeyError:
                continue
            if size != (0, 0):
                break
        width, height = size or (200, 200)

        tmpdir = tempfile.TemporaryDirectory()
        with imageio.get_writer(outfile, format=self.format, mode="I", fps=self.fps) as writer:
            for i, product in enumerate(self.products):
                # Note: imageio supports loading FITS images natively, but does
                # not support compressed FITS. See https://github.com/imageio/imageio/pull/458
                # In the mean time, convert .fits.fz to a temporary JPG first
                tmpfile = os.path.join(tmpdir.name, 'frame_{}.jpg').format(i)
                fits_to_jpg(product.data.path, tmpfile, width=width, height=height)
                writer.append_data(imageio.imread(tmpfile))
        tmpdir.cleanup()

    def get_name(self, base):
        """
        Return the filename for the timelapse file
        """
        extension = self.format
        return '{}.{}'.format(base, extension)

    def create_dataproduct(self):
        """
        Create and return a DataProduct for the timelapse
        """
        # TODO: construct a more human-readable ID
        now = datetime.now()
        product_id = 'timelapse_{}_{}_{}'.format(
            self.target.pk, self.obs.pk, now.strftime('%Y-%m-%d-%H%M%S')
        )
        prod = DataProduct(
            product_id=product_id,
            target=self.target,
            observation_record=self.obs,
            tag=IMAGE_FILE[0]
        )
        buf = BytesIO()
        self.create(buf)
        prod.data.save(self.get_name(product_id), File(buf), save=True)
        return prod

    @classmethod
    def sort_products(cls, products):
        """
        Return the sequence of DataProduct objects sorted by the date stored in
        the FITS header
        """
        def sort_key(product):
            hdus = fits.open(product.data.path)
            dt_str = hdus[0].header[cls.fits_date_field]
            return datetime.fromisoformat(dt_str)

        return sorted(products, key=sort_key)
