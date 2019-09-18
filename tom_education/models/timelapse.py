from datetime import datetime
from io import BytesIO
import os.path
import tempfile

from astroscrappy import detect_cosmics
from astropy.io import fits
import astropy.stats
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import models
from fits2image.conversions import fits_to_jpg
import imageio

from tom_dataproducts.models import DataProduct
from tom_education.models.async_process import AsyncError, AsyncProcess, ASYNC_STATUS_CREATED
from tom_education.utils import assert_valid_suffix


TIMELAPSE_GIF = 'gif'
TIMELAPSE_MP4 = 'mp4'
TIMELAPSE_WEBM = 'webm'


class DateFieldNotFoundError(Exception):
    """
    The FITS header to obtain observation date was not found
    """


class TimelapseDataProduct(DataProduct):
    """
    A timelapse data product created from other data products
    """
    FORMAT_CHOICES = (
        (TIMELAPSE_GIF, 'GIF'),
        (TIMELAPSE_MP4, 'MP4'),
        (TIMELAPSE_WEBM, 'WebM')
    )
    FITS_DATE_FIELD = 'DATE-OBS'

    frames = models.ManyToManyField(DataProduct, related_name='timelapse')
    fmt = models.CharField(max_length=10, choices=FORMAT_CHOICES, default=TIMELAPSE_GIF, blank=False)
    fps = models.FloatField(default=10, blank=False)

    def clean(self):
        super().clean()
        if self.fps <= 0:
            raise ValidationError("FPS must be positive")

    def get_filename(self):
        return f'{self.product_id}.{self.fmt}'

    def save(self, *args, **kwargs):
        self.clean()
        # Create empty placeholder data file
        if not self.data:
            self.data.save(self.get_filename(), File(BytesIO()), save=False)
        super().save(*args, **kwargs)

    def write(self):
        """
        Create the timelapse and write the file to the data attribute. Note
        that this does not save the model instance.
        """
        if not self.frames.all().exists():
            raise ValueError('Empty data products list')
        # Check input files look like FITS data
        for prod in self.frames.all():
            assert_valid_suffix(os.path.basename(prod.data.name), ['.fits', '.fz'])

        buf = BytesIO()
        self._write(buf)
        self.data.delete(save=False)
        self.data.save(self.get_filename(), File(buf), save=False)

    def _write(self, outfile):
        """
        Write the timelapse to the given output file, which may be a path or
        file-like object
        """
        writer_kwargs = {
            'format': self.fmt,
            'mode': 'I',
            'fps': self.fps
        }

        # When saving to MP4 or WebM, imageio uses ffmpeg, which determines
        # output format from file extension. When using a BytesIO buffer,
        # imageio creates a temporary file with no extension, so the ffmpeg
        # call fails. We need to specify the output format explicitly instead
        # in this case
        if self.fmt in (TIMELAPSE_MP4, TIMELAPSE_WEBM):
            writer_kwargs['output_params'] = ['-f', self.fmt]

            # Need to specify codec for WebM
            if self.fmt == TIMELAPSE_WEBM:
                writer_kwargs['codec'] = 'vp8'

            # The imageio plugin does not recognise webm as a format, so set
            # 'format' to 'mp4' in either case (this does not affect the ffmpeg
            # call)
            writer_kwargs['format'] = TIMELAPSE_MP4

        tl_settings = self.get_settings()
        image_size = tl_settings.get('size', 500)

        with tempfile.TemporaryDirectory() as tmpdir:
            with imageio.get_writer(outfile, **writer_kwargs) as writer:
                for i, product in enumerate(self.sorted_frames()):
                    fits_path = product.data.path

                    # Determine which modifiers to apply to the frame (if any).
                    # A modifier is a function that takes a HDUList as an
                    # argument and modifies it in some way
                    modifiers = []
                    crop_settings = tl_settings.get('crop')
                    if crop_settings and crop_settings.get('enabled'):
                        scale = crop_settings.get('scale', 0.5)
                        modifiers.append(lambda hdul: crop_image(hdul, scale))

                    if tl_settings.get('normalise_background'):
                        modifiers.append(normalise_background)

                    if modifiers:
                        hdul = fits.open(fits_path)

                        for mod in modifiers:
                            try:
                                mod(hdul)
                            except ValueError as ex:  # Re-raise to add filename in error message
                                raise ValueError(
                                    "Error in file '{}': {}".format(product.data.name, ex)
                                )

                        fits_path = os.path.join(tmpdir, 'tmp.fits')
                        with open(fits_path, 'wb') as f:
                            hdul.writeto(f)

                    # Note: imageio supports loading FITS files, but does not
                    # choose brightness levels intelligently. Use fits_to_jpg
                    # instead to go FITS -> JPG -> timelapse
                    jpg_path = os.path.join(tmpdir, 'frame_{}.jpg'.format(i))
                    fits_to_jpg(fits_path, jpg_path, width=image_size, height=image_size)
                    writer.append_data(imageio.imread(jpg_path))

    def sorted_frames(self):
        """
        Return the sequence of DataProduct objects sorted by the date stored in
        the FITS header
        """
        def sort_key(product):
            for hdu in fits.open(product.data.path):
                try:
                    dt_str = hdu.header[self.FITS_DATE_FIELD]
                except KeyError:
                    continue
                return datetime.fromisoformat(dt_str)
            raise DateFieldNotFoundError(
                "Error in file '{}': could not find observation date in FITS header '{}'"
                .format(product.data.name, self.FITS_DATE_FIELD)
            )

        return sorted(self.frames.all(), key=sort_key)

    @classmethod
    def create_timestamped(cls, target, frames):
        """
        Create and return a timelapse for the given target and frames, where
        format/FPS settings are taken from settings.py and the current date and
        time is used to construct the product ID
        """
        tl_settings = cls.get_settings()
        fmt = tl_settings.get('format')
        fps = tl_settings.get('fps')

        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d-%H%M%S')
        product_id = 'timelapse_{}_{}'.format(target.identifier, date_str)

        tl = TimelapseDataProduct.objects.create(
            product_id=product_id,
            target=target,
            tag='timelapse',
            fmt=fmt,
            fps=fps,
        )
        tl.frames.add(*frames)
        tl.save()
        return tl

    @classmethod
    def get_settings(cls):
        return getattr(settings, 'TOM_EDUCATION_TIMELAPSE_SETTINGS', {})


class TimelapseProcess(AsyncProcess):
    """
    Asynchronous process that calls the write() method on a
    TimelapseDataProduct
    """
    timelapse_product = models.ForeignKey(TimelapseDataProduct, on_delete=models.CASCADE, null=False)

    def run(self):
        # Run write() and convert exceptions to AsyncError for calling code to
        # handle
        try:
            self.timelapse_product.write()
        except (DateFieldNotFoundError, AssertionError) as ex:
            raise AsyncError(str(ex))
        except ValueError as ex:
            print('warning: ValueError: {}'.format(ex))
            raise AsyncError('Invalid parameters. Are all images the same size?')
        self.status = ASYNC_STATUS_CREATED
        self.save()


def get_data_index(hdul):
    """
    Get the index of the data HDU in the given HDUList, and return (i, data).
    Raises ValueError if no data HDU is found
    """
    for i, hdu in enumerate(hdul):
        if hdu.data is not None and hdu.data.ndim == 2:
            return (i, hdu.data)
    raise ValueError('no data HDU found')


def normalise_background(hdul):
    """
    Normalise the background brightness level across the data HDU in the given
    HDUList
    """
    idx, data = get_data_index(hdul)

    # Remove negative values and cosmic rays
    # TODO: get parameters for detect_cosmics and sigma_clip from settings
    _, imdata = detect_cosmics(
        data.clip(0, None), sigclip=3, sigfrac=0.05, objlim=1
    )
    # Perform sigma clipping to normalise background brightness
    clipped = astropy.stats.sigma_clip(imdata, sigma=3, maxiters=10)
    data -= clipped.filled(0)


def crop_image(hdul, scale):
    """
    Crop the image in the given HDUList around the centre point. If the
    original size is (W, H), the cropped size will be (scale * W, scale * H).
    """
    if scale < 0 or scale > 1:
        raise ValueError("scale must be in [0, 1]")
    idx, data = get_data_index(hdul)
    h, w = data.shape
    half_h = int(h * 0.5 * scale)
    half_w = int(w * 0.5 * scale)

    mid_y = int(h / 2)
    mid_x = int(w / 2)

    hdul[idx].data = data[mid_y - half_h:mid_y + half_h, mid_x - half_w:mid_x + half_w]
    new_h, new_w = hdul[idx].data.shape
    hdul[idx].header['NAXIS1'] = new_w
    hdul[idx].header['NAXIS2'] = new_h
