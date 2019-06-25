from datetime import datetime
from io import BytesIO
import os.path

from astropy.io import fits
from django.core.files import File
from django.conf import settings
import imageio
from tom_dataproducts.models import DataProduct, IMAGE_FILE


class DateFieldNotFoundError(Exception):
    """
    The FITS header to obtain observation date was not found
    """


class Timelapse:
    """
    Class to create an animated timelapse from a sequence of FITS image files
    """
    fits_date_field = 'DATE-OBS'
    valid_formats = ('gif', 'mp4', 'webm')

    def __init__(self, products, fmt=None, fps=None):
        self.products = Timelapse.sort_products(products)
        if not self.products:
            raise ValueError('Empty data products list')

        try:
            defaults = settings.TOM_EDUCATION_TIMELAPSE_SETTINGS
        except AttributeError:
            defaults = {}

        self.format = fmt or defaults.get('format', 'gif')
        self.fps = fps or defaults.get('fps', 10)

        if not self.format in self.valid_formats:
            raise ValueError('Invalid format \'{}\''.format(self.format))

        # Check that all products have a common target
        targets = {prod.target for prod in self.products}
        if len(targets) > 1:
            raise ValueError(
                'Cannot create a timelapse for data products from different targets'
            )
        self.target = list(targets)[0]

    def create(self, outfile):
        """
        Create the timelapse output file. `outfile` may be a path or file-like
        object
        """
        writer_kwargs = {
            'format': self.format,
            'mode': 'I',
            'fps': self.fps
        }

        # When saving to MP4 or WebM, imageio uses ffmpeg, which determines
        # output format from file extension. When using a BytesIO buffer,
        # imageio creates a temporary file with no extension, so the ffmpeg
        # call fails. We need to specify the output format explicitly instead
        # in this case
        if self.format in ('mp4', 'webm'):
            writer_kwargs['output_params'] = ['-f', self.format]

            # Need to specify codec for WebM
            if self.format == 'webm':
                writer_kwargs['codec'] = 'vp8'

            # The imageio plugin does not recognise webm as a format, so set
            # 'format' to 'mp4' in either case (this does not affect the ffmpeg
            # call)
            writer_kwargs['format'] = 'mp4'

        with imageio.get_writer(outfile, **writer_kwargs) as writer:
            for i, product in enumerate(self.products):
                writer.append_data(imageio.imread(product.data.path, format='fits'))

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
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d-%H%M%S')
        product_id = 'timelapse_{}_{}'.format(self.target.identifier, date_str)
        prod = DataProduct(
            product_id=product_id,
            target=self.target,
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
            for hdu in fits.open(product.data.path):
                try:
                    dt_str = hdu.header[cls.fits_date_field]
                except KeyError:
                    continue
                return datetime.fromisoformat(dt_str)
            raise DateFieldNotFoundError(product.data.name)

        return sorted(products, key=sort_key)
