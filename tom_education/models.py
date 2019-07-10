from datetime import datetime
from io import BytesIO
from urllib.parse import urlparse, parse_qs, urlunparse

from astropy.io import fits
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import models
from django.utils.http import urlencode
import imageio
from tom_dataproducts.models import DataProduct, IMAGE_FILE
from tom_targets.models import Target


ASYNC_STATUS_PENDING = 'pending'
ASYNC_STATUS_CREATED = 'created'
ASYNC_STATUS_FAILED = 'failed'

TIMELAPSE_GIF = 'gif'
TIMELAPSE_MP4 = 'mp4'
TIMELAPSE_WEBM = 'webm'


class ObservationTemplate(models.Model):
    name = models.CharField(max_length=255, null=False)
    target = models.ForeignKey(Target, on_delete=models.CASCADE, null=False)
    facility = models.CharField(max_length=255, null=False)
    # Form fields serialized as a JSON string
    fields = models.TextField()

    class Meta:
        unique_together = ('name', 'target', 'facility')

    def get_create_url(self, base_url):
        """
        Return URL for instantiating this template by adding 'template_id' GET
        parameter to base create URL
        """
        # Need to parse base URL and combine GET parameters
        parsed_url = urlparse(base_url)
        params = parse_qs(parsed_url.query)
        for key, val in params.items():
            params[key] = val[0]
        params['template_id'] = self.pk
        parts = list(parsed_url)
        parts[4] = urlencode(params)
        return urlunparse(parts)

    def get_identifier(self):
        """
        Return an identifier for an instantiation of this template, based on
        the template name and current date and time
        """
        now = datetime.now()
        fmt = '%Y-%m-%d-%H%M%S'
        return "{}-{}".format(self.name, now.strftime(fmt))


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

        with imageio.get_writer(outfile, **writer_kwargs) as writer:
            for product in self.sorted_frames():
                writer.append_data(imageio.imread(product.data.path, format='fits'))

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
                'Could not find observation date in FITS header \'{}\' in file \'{}\''
                .format(self.FITS_DATE_FIELD, product.data.name)
            )

        return sorted(self.frames.all(), key=sort_key)

    @classmethod
    def create_timestamped(cls, target, frames):
        """
        Create and return a timelapse for the given target and frames, where
        format/FPS settings are taken from settings.py and the current date and
        time is used to construct the product ID
        """
        tl_settings = getattr(settings, 'TOM_EDUCATION_TIMELAPSE_SETTINGS', {})
        fmt = tl_settings.get('format')
        fps = tl_settings.get('fps')

        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d-%H%M%S')
        product_id = 'timelapse_{}_{}'.format(target.identifier, date_str)

        tl = TimelapseDataProduct.objects.create(
            product_id=product_id,
            target=target,
            tag=IMAGE_FILE[0],
            fmt=fmt,
            fps=fps,
        )
        tl.frames.add(*frames)
        tl.save()
        return tl


class AsyncError(Exception):
    """
    An error occurred in an asynchronous process
    """


class AsyncProcess(models.Model):
    STATUS_CHOICES = (
        (ASYNC_STATUS_PENDING, 'Pending'),
        (ASYNC_STATUS_CREATED, 'Created'),
        (ASYNC_STATUS_FAILED, 'Failed')
    )
    identifier = models.CharField(null=False, blank=False, max_length=50, unique=True)
    status = models.CharField(
        max_length=50, choices=STATUS_CHOICES, default=ASYNC_STATUS_PENDING
    )
    failure_message = models.CharField(max_length=255, blank=True)
    # Process may optionally be associated with a target
    target = models.ForeignKey(Target, on_delete=models.CASCADE, null=True)

    def run():
        """
        Perform the potentially long-running task. Should raise AsyncError with
        an appropriate error message on failure.
        """
        raise NotImplementedError


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
        except DateFieldNotFoundError as ex:
            raise AsyncError(str(ex))
        except ValueError as ex:
            print('warning: ValueError: {}'.format(ex))
            raise AsyncError('Invalid parameters. Are all images the same size?')
        self.status = ASYNC_STATUS_CREATED
        self.save()
