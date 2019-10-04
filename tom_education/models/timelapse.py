from datetime import datetime
from io import BytesIO
import os.path
import tempfile
import logging

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
from tom_education.models.async_process import AsyncError
from tom_education.models.pipelines import PipelineProcess, PipelineOutput
from tom_education.utils import assert_valid_suffix


TIMELAPSE_GIF = 'gif'
TIMELAPSE_MP4 = 'mp4'
TIMELAPSE_WEBM = 'webm'
TIMELAPSE_TAG = 'timelapse'

logger = logging.getLogger(__name__)

class TimelapsePipeline(PipelineProcess):
    """
    Pipeline process to make a timelapse from a sequence of FITS images
    """
    short_name = 'tl'
    allowed_suffixes = ['.fits', '.fz']
    flags = {
        'normalise_background': {
            'default': False,
            'long_name': ('Process each frame to achieve a consistent '
                          'background brightness across the timelapse')
        },

        'crop': {
            'default': False,
            'long_name': 'Crop each frame in the timelapse around its centre pixel'
        }
    }

    FITS_DATE_FIELD = 'DATE-OBS'

    class Meta:
        proxy = True

    def do_pipeline(self, tmpdir, **flags):
        tl_settings = self.get_settings()
        fmt = tl_settings.get('format', TIMELAPSE_GIF)
        fps = tl_settings.get('fps', 10)
        image_size = tl_settings.get('size', 500)
        if fps <= 0:
            raise AsyncError(f'Invalid FPS {fps}')

        # Filenames for pipeline-produced files include the pipeline
        # identifier, so keep this name short
        outfile = tmpdir / f't.{fmt}'

        with outfile.open('wb') as f:
            try:
                self.write_timelapse(f, fmt, fps, image_size, **flags)
            except ValueError as ex:
                logger.error('ValueError: {}'.format(ex))
                raise AsyncError('Invalid parameters. Are all images the same size?')

        return [PipelineOutput(outfile, DataProduct, TIMELAPSE_TAG)]

    def write_timelapse(self, outfile, fmt=TIMELAPSE_GIF, fps=10,
                        image_size=500, **flags):
        """
        Write the timelapse to the given output file, which may be a path or
        file-like object
        """
        writer_kwargs = {
            'format': fmt,
            'mode': 'I',
            'fps': fps
        }

        # When saving to MP4 or WebM, imageio uses ffmpeg, which determines
        # output format from file extension. When using a BytesIO buffer,
        # imageio creates a temporary file with no extension, so the ffmpeg
        # call fails. We need to specify the output format explicitly instead
        # in this case
        if fmt in (TIMELAPSE_MP4, TIMELAPSE_WEBM):
            writer_kwargs['output_params'] = ['-f', fmt]

            # Need to specify codec for WebM
            if fmt == TIMELAPSE_WEBM:
                writer_kwargs['codec'] = 'vp8'

            # The imageio plugin does not recognise webm as a format, so set
            # 'format' to 'mp4' in either case (this does not affect the ffmpeg
            # call)
            writer_kwargs['format'] = TIMELAPSE_MP4

        num_frames = self.input_files.count()

        with tempfile.TemporaryDirectory() as tmpdir:
            with imageio.get_writer(outfile, **writer_kwargs) as writer:
                for i, product in enumerate(self.sorted_frames()):
                    self.log(f'Processing frame {i + 1}/{num_frames}')

                    fits_path = product.data.file
                    if flags.get('normalise_background') or flags.get('crop'):
                        fits_path.open()
                        data, header = fits.getdata(fits_path, header=True)
                        fits_path.close()
                        try:
                            if flags.get('crop'):
                                scale = self.get_settings().get('crop_scale', 0.5)
                                data, header = crop_image(data, header, scale)
                            if flags.get('normalise_background'):
                                data = normalise_background(data, header)

                        except ValueError as ex:
                            raise AsyncError(
                                "Error in file '{}': {}".format(product.data.name, ex)
                            )
                        fits_path = os.path.join(tmpdir, 'tmp.fits')
                        hdul = fits.HDUList([fits.PrimaryHDU(data, header=header)])
                        with open(fits_path, 'wb') as f:
                            hdul.writeto(f)

                    # Note: imageio supports loading FITS files, but does not
                    # choose brightness levels intelligently. Use fits_to_jpg
                    # instead to go FITS -> JPG -> timelapse
                    jpg_path = os.path.join(tmpdir, 'frame_{}.jpg'.format(i))
                    fits_to_jpg(fits_path, jpg_path, width=image_size, height=image_size)
                    writer.append_data(imageio.imread(jpg_path))

        self.log('Finished')

    def sorted_frames(self):
        """
        Return the sequence of DataProduct objects sorted by the date stored in
        the FITS header
        """
        def sort_key(product):
            product.data.file.open()
            for hdu in fits.open(product.data.file):
                try:
                    dt_str = hdu.header[self.FITS_DATE_FIELD]
                except KeyError:
                    continue
                product.data.file.close()
                return datetime.fromisoformat(dt_str)
            raise AsyncError(
                "Error in file '{}': could not find observation date in FITS header '{}'"
                .format(product.data.name, self.FITS_DATE_FIELD)
            )

        return sorted(self.input_files.all(), key=sort_key)

    @classmethod
    def get_settings(cls):
        return getattr(settings, 'TOM_EDUCATION_TIMELAPSE_SETTINGS', {})

def get_data_index(hdul):
    """
    Get the index of the data HDU in the given HDUList, and return (i, data).
    Raises ValueError if no data HDU is found
    """
    for i, hdu in enumerate(hdul):
        if hdu.data is not None and hdu.data.ndim == 2:
            return (i, hdu.data)
    raise ValueError('no data HDU found')

def normalise_background(data, header):
    """
    Normalise the background brightness level across the data HDU in the given
    HDUList
    """

    # Remove negative values and cosmic rays
    # TODO: get parameters for detect_cosmics and sigma_clip from settings

    _, imdata = detect_cosmics(
        data.clip(0, None), sigclip=3, sigfrac=0.05, objlim=1
    )
    # Perform sigma clipping to normalise background brightness
    clipped = astropy.stats.sigma_clip(imdata, sigma=3, maxiters=10)
    data -= clipped.filled(0)
    return data

def crop_image(data, header, scale):
    """
    Crop the image in the given HDUList around the centre point. If the
    original size is (W, H), the cropped size will be (scale * W, scale * H).
    """
    if scale < 0 or scale > 1:
        raise ValueError("scale must be in [0, 1]")
    # idx, data = get_data_index(hdul)
    h, w = data.shape
    half_h = int(h * 0.5 * scale)
    half_w = int(w * 0.5 * scale)

    mid_y = int(h / 2)
    mid_x = int(w / 2)

    data = data[mid_y - half_h:mid_y + half_h, mid_x - half_w:mid_x + half_w]
    new_h, new_w = data.shape
    header['NAXIS1'] = new_w
    header['NAXIS2'] = new_h
    return data, header
