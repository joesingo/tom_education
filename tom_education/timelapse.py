from datetime import datetime
from io import BytesIO

from astropy.io import fits
from django.core.files import File
import imageio
from tom_dataproducts.models import DataProduct

from tom_education.models import TIMELAPSE_CREATED


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

    def __init__(self, product_pks, fmt, fps):
        self.products = Timelapse.sort_products(
            DataProduct.objects.get(pk=pk) for pk in product_pks
        )
        if not self.products:
            raise ValueError('Empty data products list')

        self.format = fmt
        if not self.format in self.valid_formats:
            raise ValueError('Invalid format \'{}\''.format(self.format))

        self.fps = fps

        # Check that all products have a common target
        targets = {prod.target for prod in self.products}
        if len(targets) > 1:
            raise ValueError(
                'Cannot create a timelapse for data products from different targets'
            )

    def _write(self, outfile):
        """
        Write the timelapse to the given output file, which may be a path or
        file-like object
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
            for product in self.products:
                writer.append_data(imageio.imread(product.data.path, format='fits'))

    def write(self, tl_prod, filename):
        """
        Create the timelapse and write it to the data attribute in the
        timelapse data product
        """
        buf = BytesIO()
        self._write(buf)
        tl_prod.data.delete()
        tl_prod.data.save(filename, File(buf))
        tl_prod.status = TIMELAPSE_CREATED
        tl_prod.save()

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
