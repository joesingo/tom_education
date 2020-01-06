from datetime import datetime
from io import BytesIO, StringIO
import json
import os
from unittest.mock import patch
import tempfile

from astropy.io import fits
from django import forms
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import File
from django.core.management import call_command
from django.conf import settings
from django.db import transaction
from django.db.models.query import QuerySet
from django.urls import reverse
from django.test import SimpleTestCase, TestCase, override_settings
from django.contrib.auth.models import User
from guardian.shortcuts import assign_perm
import imageio
import numpy as np
from tom_dataproducts.models import DataProduct, ReducedDatum, DataProductGroup
from tom_targets.models import Target
from tom_observations.models import ObservationRecord
from tom_observations.tests.factories import ObservingRecordFactory
from tom_observations.tests.utils import FakeFacility, FakeFacilityForm

from tom_education.forms import DataProductActionForm, GalleryForm
from tom_education.facilities import EducationLCOForm
from tom_education.models import (
    ASYNC_STATUS_CREATED,
    ASYNC_STATUS_FAILED,
    ASYNC_STATUS_PENDING,
    AsyncError,
    AsyncProcess,
    crop_image,
    InvalidPipelineError,
    ObservationAlert,
    ObservationTemplate,
    PipelineProcess,
    PipelineOutput,
    TIMELAPSE_GIF,
    TIMELAPSE_MP4,
    TIMELAPSE_WEBM,
    TimelapsePipeline,
)
from tom_education.templatetags.tom_education_extras import dataproduct_selection_buttons
from tom_education.tasks import run_pipeline


class FakeTemplateFacilityForm(FakeFacilityForm):
    # Add some extra fields so we can check that the correct field is used as
    # the identifier
    extra_field = forms.CharField()
    another_extra_field = forms.IntegerField()

    def get_extra_context(self):
        return {'extra_variable_from_form': 'hello'}


class FakeTemplateFacility(FakeFacility):
    name = 'TemplateFake'

    def get_form(self, *args):
        return FakeTemplateFacilityForm


class AnotherFakeFacility(FakeFacility):
    name = 'AnotherFake'

    def get_form(self, *args):
        return FakeTemplateFacilityForm


FAKE_FACILITIES = [
    'tom_education.tests.FakeTemplateFacility',
    'tom_education.tests.AnotherFakeFacility',
]


def write_fits_image_file(data, date=None):
    primary_hdu = fits.PrimaryHDU()
    primary_hdu.header['XTENSION'] = 'IMAGE'
    if date:
        primary_hdu.header['DATE-OBS'] = date.isoformat()
    img = fits.hdu.compressed.CompImageHDU(data)
    hdul = fits.HDUList([primary_hdu, img])
    buf = BytesIO()
    hdul.writeto(buf)
    return buf


class TestDataHandler:
    """
    Small class to handle creating and deleting temporary directories to use as
    the `MEDIA_ROOT` setting for data files created during tests.

    Provides a `media_root` property which returns the path to the temp dir.
    """
    def __init__(self):
        self.tmpdir = None
        self.create()

    def create(self):
        if not self.tmpdir:
            self.tmpdir = tempfile.TemporaryDirectory()

    def delete(self):
        self.tmpdir.cleanup()
        self.tmpdir = None

    @property
    def media_root(self):
        return self.tmpdir.name


TEST_DATA_HANDLER = TestDataHandler()


@override_settings(MEDIA_ROOT=TEST_DATA_HANDLER.media_root)
class TomEducationTestCase(TestCase):
    """
    Base class for tom_education tests
    """
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        TEST_DATA_HANDLER.create()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        TEST_DATA_HANDLER.delete()


@override_settings(TOM_FACILITY_CLASSES=FAKE_FACILITIES)
@patch('tom_education.models.ObservationTemplate.get_identifier_field', return_value='test_input')
@patch('tom_education.views.TemplatedObservationCreateView.supported_facilities', ('TemplateFake',))
class ObservationTemplateTestCase(TomEducationTestCase):
    facility = 'TemplateFake'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create(username='someuser', password='somepass', is_staff=True)
        cls.non_staff = User.objects.create(username='another', password='aaa')
        cls.target = Target.objects.create(name='my target')

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def get_base_url(self, facility=None):
        # Return URL for create form without target ID
        facility = facility or self.facility
        return reverse('tom_education:create_obs', kwargs={'facility': facility})

    def get_url(self, target, facility=None):
        return '{}?target_id={}'.format(self.get_base_url(facility), target.pk)

    def test_existing_templates_shown(self, mock):
        template = ObservationTemplate.objects.create(
            name='mytemplate',
            target=self.target,
            facility=self.facility,
            fields='{"one": "two"}'
        )
        # Make another template for a different facility: should not be shown
        template2 = ObservationTemplate.objects.create(
            name='other-template',
            target=self.target,
            facility='made up facility',
            fields='{"1": "2"}'
        )

        response = self.client.get(self.get_url(self.target))
        self.assertEqual(response.status_code, 200)

        self.assertIn(b'mytemplate', response.content)
        self.assertNotIn(b'other-template', response.content)

        # Go to create page for a different target: template should not be
        # shown
        target2 = Target.objects.create(name='another')
        response2 = self.client.get(self.get_url(target2))
        self.assertEqual(response2.status_code, 200)
        self.assertNotIn(b'mytemplate', response2.content)

    def test_create_button(self, mock):
        response = self.client.get(self.get_url(self.target))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'create-template', response.content)
        self.assertIn(b'Create new template', response.content)

        # Should not be present if facility not supported
        response2 = self.client.get(self.get_url(self.target, facility='AnotherFake'))
        self.assertEqual(response2.status_code, 200)
        self.assertNotIn(b'create-template', response2.content)
        self.assertNotIn(b'Create new template', response2.content)

        # Should not be present as non-staff
        self.client.force_login(self.non_staff)
        response3 = self.client.get(self.get_url(self.target))
        self.assertEqual(response3.status_code, 200)
        self.assertNotIn(b'create-template', response3.content)
        self.assertNotIn(b'Create new template', response3.content)

    def test_create_template(self, mock):
        self.assertEqual(ObservationTemplate.objects.all().count(), 0)
        fields = {
            'test_input': 'some-name',
            'extra_field': 'this is some extra text',
            'another_extra_field': 4,
            'target_id': self.target.pk,
            'facility': self.facility,
            'observation_type': '',
        }
        post_params = dict(fields, **{
            'create-template': 'yes please'
        })

        # Should not be able to POST as non-staff user
        self.client.force_login(self.non_staff)
        response = self.client.post(self.get_base_url(), post_params)
        self.assertEqual(response.status_code, 403)

        # Should not be able to POST if facility is not supported
        self.client.force_login(self.user)
        wrong_facility = dict(post_params, facility='AnotherFake')
        response2 = self.client.post(self.get_base_url(facility='AnotherFake'), wrong_facility)
        self.assertEqual(response2.status_code, 403)

        # Should be able to create as staff user for a valid facility
        response3 = self.client.post(self.get_base_url(), post_params)
        self.assertEqual(response3.status_code, 302)
        self.assertEqual(response3.url, self.get_url(self.target) + '&template_id=1')

        # ObservationTemplate object should have been created
        self.assertEqual(ObservationTemplate.objects.all().count(), 1)
        template = ObservationTemplate.objects.all()[0]

        self.assertEqual(template.name, 'some-name')
        self.assertEqual(template.target, self.target)
        self.assertEqual(template.facility, self.facility)
        self.assertEqual(json.loads(template.fields), fields)

    @patch('tom_education.models.observation_template.datetime')
    def test_instantiate_template(self, dt_mock, _):
        dt_mock.now.return_value = datetime(
            year=2019, month=1, day=2, hour=3, minute=4, second=5, microsecond=6
        )

        template = ObservationTemplate.objects.create(
            name='mytemplate',
            target=self.target,
            facility=self.facility,
            fields='{"test_input": "mytemplate", "extra_field": "someextravalue", '
                   '"another_extra_field": 5}'
        )
        url = self.get_url(self.target) + '&template_id=' + str(template.pk)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        initial = response.context['form'].initial
        self.assertEqual(initial['test_input'], 'mytemplate-2019-01-02-030405')
        self.assertEqual(initial['extra_field'], 'someextravalue')
        self.assertEqual(initial['another_extra_field'], 5)

    def test_extra_form_context(self, mock):
        response = self.client.get(self.get_url(self.target))
        self.assertIn('extra_variable_from_form', response.context)


# The following test causes an error if run in a DB transaction since it
# causes an IntegrityError, after which no more DB queries can be performed.
# To work around this, put the test in its own SimpleTestCase so that no
# transaction is used
@override_settings(TOM_FACILITY_CLASSES=FAKE_FACILITIES)
@patch('tom_education.models.ObservationTemplate.get_identifier_field', return_value='test_input')
@patch('tom_education.views.TemplatedObservationCreateView.supported_facilities', ('TemplateFake',))
class InvalidObservationTemplateNameTestCase(SimpleTestCase):
    databases = '__all__'

    def setUp(self):
        super().setUp()

    def test_invalid_template_name(self, mock):
        user = User.objects.create(username='someuser', password='somepass', is_staff=True)
        self.client.force_login(user)

        target = Target.objects.create(name='my target')
        template = ObservationTemplate.objects.create(
            name="cool-template-name",
            target=target,
            facility='TemplateFake',
            fields='...'
        )

        url = reverse('tom_education:create_obs', kwargs={'facility': 'TemplateFake'})
        response = self.client.post(url, {
            'test_input': 'cool-template-name',
            'extra_field': 'blah',
            'another_extra_field': 4,
            'target_id': target.pk,
            'facility': 'TemplateFake',
            'create-template': 'yep'
        })
        self.assertEqual(response.status_code, 200)

        err_msg = 'Template name "cool-template-name" already in use'
        self.assertIn(err_msg, response.context['form'].errors['__all__'])

        # Double check that no template was created
        temp_count = ObservationTemplate.objects.all().count()
        self.assertEqual(temp_count, 1)


@override_settings(TOM_FACILITY_CLASSES=['tom_observations.tests.utils.FakeFacility'])
class DataProductTestCase(TomEducationTestCase):
    """
    Class providing a setUpClass method which creates a target, observation
    record and several FITS data products
    """
    # Shape for dummy FITS files created in setUpClass
    test_fits_shape = (500, 50)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.target = Target.objects.create(name='my target')
        cls.observation_record = ObservingRecordFactory.create(
            target_id=cls.target.id,
            facility=FakeFacility.name,
            parameters='{}'
        )

        # Create some FITS image files and DataProducts from them
        cls.prods = []

        dates = [  # Note: dates are not in order
            datetime(year=2019, month=1, day=2, hour=3, minute=4),
            datetime(year=2019, month=1, day=2, hour=3, minute=5),
            datetime(year=2019, month=1, day=2, hour=3, minute=7),
            datetime(year=2019, month=1, day=2, hour=3, minute=6)
        ]
        # Create dummy image data. Make sure data is not constant to avoid
        # warnings from fits2image
        # TODO: consider using real fits files here...
        cls.image_data = np.ones(cls.test_fits_shape, dtype=np.float)
        cls.image_data[20, :] = np.linspace(1, 100, num=50)

        for i, date in enumerate(dates):
            product_id = 'test{}'.format(i)
            prod = DataProduct.objects.create(
                product_id=product_id,
                target=cls.target,
                observation_record=cls.observation_record,
            )
            buf = write_fits_image_file(cls.image_data, date)
            prod.data.save('{}.fits.fz'.format(product_id), File(buf), save=True)
            cls.prods.append(prod)

            # Save pk to class for convinience
            setattr(cls, 'pk{}'.format(i), str(prod.pk))


class TargetDataViewTestCase(DataProductTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='test', email='test@example.com')
        self.client.force_login(self.user)
        assign_perm('tom_targets.view_target', self.user, self.target)
        self.url = reverse('tom_education:target_data', kwargs={'pk': self.target.pk})

    def test_selection_buttons(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Select all', response.content)
        self.assertIn(b'Select reduced', response.content)
        self.assertIn(b'Deselect all', response.content)

    def test_data_product_group_selection(self):
        group1 = DataProductGroup.objects.create(name='First group')
        group2 = DataProductGroup.objects.create(name='Second group')
        group3 = DataProductGroup.objects.create(name='Third group')
        self.prods[0].group.add(group1)
        self.prods[1].group.add(group1, group2)
        self.prods[2].group.add(group2)
        self.prods[0].save()
        self.prods[1].save()
        self.prods[2].save()

        # First test the inclusion tag which provides the list of groups for
        # the page
        ctx = {'target': self.target}
        self.assertNotIn('data_product_groups', dataproduct_selection_buttons(ctx, False))
        button_context = dataproduct_selection_buttons(ctx, True)
        self.assertIn('data_product_groups', button_context)
        # Group 3 should not be included, since no DPs for this target are part
        # of it
        self.assertEqual(len(button_context['data_product_groups']), 2)
        self.assertEqual(set(button_context['data_product_groups']), {group1, group2})

        # Test the view and the rendered HTML
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Select group', response.content)
        self.assertIn(b'First group', response.content)
        self.assertIn(b'Second group', response.content)
        self.assertIn(b'dpgroup-1', response.content)
        self.assertIn(b'dpgroup-2', response.content)

    def test_null_product_id(self):
        """
        The data product action buttons should still work with products with
        None product_id (unfortunately, such data products may exist -- e.g.
        ones created by a user uploading a file)
        """
        dp1 = DataProduct.objects.create(product_id='hello', target=self.target)
        dp2 = DataProduct.objects.create(target=self.target)

        dp1.data.save('file1', File(BytesIO()))
        dp1.data.save('file2', File(BytesIO()))

        response = self.client.post(self.url, data={
            'action': 'view_gallery',
            dp1.pk: 'on',
            dp2.pk: 'on'
        })


def mock_fits_to_jpg(inputfiles, outputfile, **kwargs):
    f = open(outputfile, 'wb')
    f.close()
    return True

@override_settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={
    'format': 'gif', 'fps': 10, 'size': 500, 'crop_scale': 0.5
})
class TimelapseTestCase(DataProductTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='test', email='test@example.com')
        self.client.force_login(self.user)
        assign_perm('tom_targets.view_target', self.user, self.target)

    def create_timelapse_pipeline(self, products, **kwargs):
        pipeline = TimelapsePipeline.objects.create(
            identifier='test_{}'.format(datetime.now().isoformat()),
            target=self.target,
            **kwargs
        )
        pipeline.input_files.add(*products)
        pipeline.save()
        return pipeline

    # Methods to check a buffer for file signatures.
    # See https://www.garykessler.net/library/file_sigs.html
    def assert_gif_data(self, data):
        data.seek(0)
        self.assertEqual(data.read(6), b'GIF89a')

    def assert_mp4_data(self, data):
        data.seek(4)
        self.assertEqual(data.read(8), b'ftypisom')

    def assert_webm_data(self, data):
        data.seek(0)
        self.assertEqual(data.read(4), b'\x1a\x45\xdf\xa3')

    @override_settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={'format': TIMELAPSE_GIF, 'fps': 16})
    @patch('tom_education.models.pipelines.datetime')
    def test_create_timelapse_form(self, dt_mock):
        """
        Test the view and form, and check that the timelapse is created
        successfully
        """
        d = datetime(
            year=2019, month=1, day=2, hour=3, minute=4, second=5, microsecond=6
        )
        dt_mock.now.return_value = d
        dt_mock.fromisoformat.return_value = d

        # GET page and check form is in the context
        url = reverse('tom_education:target_data', kwargs={'pk': self.target.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('dataproducts_form', response.context)
        self.assertIsInstance(response.context['dataproducts_form'], DataProductActionForm)

        pre_tlpipe_count = TimelapsePipeline.objects.count()
        self.assertEqual(pre_tlpipe_count, 0)
        self.assertFalse(DataProduct.objects.filter(data_product_type=settings.DATA_PRODUCT_TYPES['timelapse'][0]).exists())

        # POST form
        response2 = self.client.post(url, {
            'action': 'pipeline',
            'pipeline_name': 'Timelapse',
            self.pk0: 'on',
            self.pk3: 'on',
            self.pk2: 'on',
        })
        # Should get JSON response
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json(), {'ok': True})

        # TimelapsePipeline object should have been created
        post_tlpipe_count = TimelapsePipeline.objects.count()
        self.assertEqual(post_tlpipe_count, pre_tlpipe_count + 1)
        pipe = TimelapsePipeline.objects.last()
        self.assertIn('Processing frame 1/3', pipe.logs)
        self.assertIn('Processing frame 2/3', pipe.logs)
        self.assertIn('Processing frame 3/3', pipe.logs)

        # DataProduct with timelapse tag should have been created
        tls = DataProduct.objects.filter(data_product_type=settings.DATA_PRODUCT_TYPES['timelapse'][0])
        self.assertTrue(tls.exists())
        dp = tls.first()

        # Check the fields are correct
        self.assertEqual(dp.target, self.target)
        self.assertEqual(dp.observation_record, None)
        self.assertEqual(dp.data_product_type, settings.DATA_PRODUCT_TYPES['timelapse'][0])
        expected_filename = 'tl_{}_20190102030405_t.gif'.format(self.target.pk)
        self.assertEqual(dp.product_id, expected_filename)
        self.assertTrue(os.path.basename(dp.data.name), expected_filename)

        # Check the timelapse data
        self.assert_gif_data(dp.data.file)

    def test_empty_form(self):
        form = DataProductActionForm(target=self.target, data={})
        self.assertFalse(form.is_valid())

        form2 = DataProductActionForm(target=self.target, data={'action': 'blah'})
        self.assertFalse(form2.is_valid())

        form3 = DataProductActionForm(target=self.target, data={self.pk0: 'on', 'action': 'blah'})
        self.assertTrue(form3.is_valid())

    def test_fits_file_sorting(self):
        correct_order = [self.prods[0], self.prods[1], self.prods[3], self.prods[2]]
        pipeline = self.create_timelapse_pipeline(self.prods)
        self.assertEqual(pipeline.sorted_frames(), correct_order)

    def test_multiple_observations(self):
        """
        Should be able to create a timelapse of data from several observations
        """
        other_obs = ObservingRecordFactory.create(
            target_id=self.target.id,
            facility=FakeFacility.name,
            parameters='{}'
        )
        other_obs_prod = DataProduct.objects.create(
            product_id='different observation',
            target=self.target,
            observation_record=other_obs,
            data=self.prods[0].data.name
        )
        pipeline = self.create_timelapse_pipeline([
            self.prods[0], self.prods[1], other_obs_prod
        ])
        pipeline.write_timelapse(BytesIO(), 'gif', 30, 500)

    def test_create_gif(self):
        pipeline = self.create_timelapse_pipeline(self.prods)
        buf = BytesIO()
        pipeline.write_timelapse(buf, fmt='gif')
        self.assert_gif_data(buf)

        # Check the number of frames is correct
        buf.seek(0)
        frames = imageio.mimread(buf)
        self.assertEqual(len(frames), len(self.prods))
        # Check the size of the first frame
        self.assertEqual(frames[0].shape, self.image_data.shape)

    def test_create_mp4(self):
        pipeline = self.create_timelapse_pipeline(self.prods)
        buf = BytesIO()
        pipeline.write_timelapse(buf, fmt='mp4')
        self.assert_mp4_data(buf)
        buf.seek(0)
        # Load and check the mp4 with imageio
        frames = imageio.mimread(buf, format='mp4')
        self.assertEqual(len(frames), len(self.prods))

    def test_create_webm(self):
        pipeline = self.create_timelapse_pipeline(self.prods)
        buf = BytesIO()
        pipeline.write_timelapse(buf, fmt='webm')
        buf.seek(0)
        self.assert_webm_data(buf)

    def test_invalid_fps(self):
        invalid_fpses = (0, -1)
        for fps in invalid_fpses:
            with self.settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={'fps': fps}):
                pip = self.create_timelapse_pipeline(self.prods)
                with self.assertRaises(AsyncError):
                    pip.run()

    @patch('tom_education.models.TimelapsePipeline.FITS_DATE_FIELD', new='hello')
    def test_no_observation_date_view(self):
        """
        Check we get the expected error when a FITS file does not contain the
        header for the date of the observation. This is achieved by patching
        the field name and setting it to 'hello'
        """
        pipeline = self.create_timelapse_pipeline(self.prods)
        with self.assertRaises(AsyncError):
            pipeline.write_timelapse(BytesIO())

    @override_settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={'format': TIMELAPSE_GIF, 'fps': 16})
    def test_run_pipeline_wrapper(self):
        pipeline = self.create_timelapse_pipeline(self.prods)
        # Cause an 'expected' error by patching date field: should get proper
        # failure message
        with patch('tom_education.models.TimelapsePipeline.FITS_DATE_FIELD', new='hello') as _mock:
            run_pipeline(pipeline.pk, 'Timelapse')
            pipeline.refresh_from_db()
            self.assertEqual(pipeline.status, ASYNC_STATUS_FAILED)
            self.assertTrue(isinstance(pipeline.failure_message, str))
            self.assertIn('could not find observation date', pipeline.failure_message)

        # Cause an 'unexpected' error: should get generic failure message
        pipeline2 = self.create_timelapse_pipeline(self.prods)
        with patch('tom_education.models.timelapse.imageio', new='hello') as _mock:
            run_pipeline(pipeline2.pk, 'Timelapse')
            pipeline2.refresh_from_db()
            self.assertEqual(pipeline2.status, ASYNC_STATUS_FAILED)
            self.assertTrue(isinstance(pipeline2.failure_message, str))
            self.assertEqual(pipeline2.failure_message, 'An unexpected error occurred')

        # Create a timelapse successfully
        pipeline3 = self.create_timelapse_pipeline(self.prods)
        run_pipeline(pipeline3.pk, 'Timelapse')
        pipeline3.refresh_from_db()
        self.assertEqual(pipeline3.status, ASYNC_STATUS_CREATED)
        self.assertTrue(pipeline3.group)
        dps = pipeline3.group.dataproduct_set.all()
        self.assertTrue(dps.exists())
        self.assert_gif_data(dps.first().data.file)

    @override_settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={'format': TIMELAPSE_GIF, 'fps': 16},
                       TOM_EDUCATION_TIMELAPSE_GROUP_NAME='timelapsey')
    def test_management_command(self):
        pre_tlpipe_count = TimelapsePipeline.objects.count()
        self.assertEqual(pre_tlpipe_count, 0)

        # Make first 3 products in timelapse group, but have the third one a
        # raw file
        group = DataProductGroup.objects.create(name='timelapsey')
        for prod in self.prods[:3]:
            prod.group.add(group)
            prod.save()
        rawfilename = 'somerawfile_{}.e00.fits.fz'.format(datetime.now().strftime('%s'))
        self.prods[2].data.save(rawfilename, File(BytesIO()), save=True)

        # Make a product in the group but for a different target: it should
        # not be included in the timelapse
        other_target = Target.objects.create(name='someothertarget')
        other_prod = DataProduct.objects.create(product_id='someotherproduct', target=other_target)
        other_prod.group.add(group)
        other_prod.save()

        buf = StringIO()
        call_command('create_timelapse', self.target.pk, stdout=buf)

        # Check timelapse pipeline object created
        post_tlpipe_count = TimelapsePipeline.objects.count()
        self.assertEqual(post_tlpipe_count, pre_tlpipe_count + 1)

        # Check fields in the pipeline look correct
        pipe = TimelapsePipeline.objects.first()
        self.assertEqual(pipe.target, self.target)
        self.assertEqual(set(pipe.input_files.all()), set(self.prods[:2]))

        # Check the timelapse itself
        tls = DataProduct.objects.filter(data_product_type=settings.DATA_PRODUCT_TYPES['timelapse'][0])
        self.assertEqual(tls.count(), 1)
        tl = tls.first()
        self.assert_gif_data(tl.data.file)

        # Check the command output
        output = buf.getvalue()
        self.assertTrue("Creating timelapse of 2 files for target 'my target'..." in output)
        self.assertTrue('Created timelapse' in output)

    @patch('tom_education.models.timelapse.TimelapsePipeline.FITS_DATE_FIELD', 'hello')
    @override_settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={'format': TIMELAPSE_GIF, 'fps': 16},
                       TOM_EDUCATION_TIMELAPSE_GROUP_NAME='timelapsey')
    def test_management_command_failure(self):
        group = DataProductGroup.objects.create(name='timelapsey')
        for prod in self.prods[:3]:
            prod.group.add(group)
            prod.save()

        buf = StringIO()
        call_command('create_timelapse', self.target.pk, stderr=buf)
        self.assertIn('could not find observation date', buf.getvalue())

    def test_management_command_no_dataproducts(self):
        buf = StringIO()
        call_command('create_timelapse', self.target.pk, stdout=buf)
        output = buf.getvalue()
        self.assertTrue('Nothing to do' in output, 'Output was: {}'.format(output))
        self.assertEqual(DataProduct.objects.filter(data_product_type=settings.DATA_PRODUCT_TYPES['timelapse'][0]).count(), 0)
        # The timelapse group should have been created
        self.assertEqual(DataProductGroup.objects.count(), 1)

    @patch('tom_education.models.timelapse.normalise_background')
    @patch('tom_education.models.timelapse.imageio.imread', return_value=np.array([[0,0,0],[0,10,0]]))
    @patch('tom_education.models.timelapse.fits_to_jpg', mock_fits_to_jpg)
    def test_background_normalisation(self, im_mock, norm_mock):
        ## TODO: Don't really understand how this test avoid exception in fit2image
        pipeline = self.create_timelapse_pipeline(self.prods)

        # With processing, the normalisation method should be called for each
        # frame
        buf = BytesIO()
        pipeline.write_timelapse(buf, normalise_background=True)
        self.assertEqual(norm_mock.call_count, len(self.prods))

        # With processing disabled, it shouldn't be called any more times
        buf = BytesIO()
        pipeline.write_timelapse(buf, normalise_background=False)
        self.assertEqual(norm_mock.call_count, len(self.prods))

    @override_settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={'crop_scale': 0.8})
    def test_timelapse_cropping(self):
        pipeline = self.create_timelapse_pipeline(self.prods)

        buf = BytesIO()
        pipeline.write_timelapse(buf, crop=True)
        buf.seek(0)
        frames = imageio.mimread(buf)
        # Check all frames are the same shape
        shape = frames[0].shape
        self.assertTrue(all(f.shape == shape for f in frames[1:]))
        # Check the shape is as expected
        self.assertEqual(
            shape,
            (int(0.8 * self.test_fits_shape[0]), int(0.8 * self.test_fits_shape[1]))
        )

        # Repeat of the above test but with cropping disabled: the shape of the
        # output frames should be identical to the shape of the inputs
        buf = BytesIO()
        pipeline.write_timelapse(buf, crop=False)
        buf.seek(0)
        frames = imageio.mimread(buf)
        shape = frames[0].shape
        self.assertTrue(all(f.shape == shape for f in frames[1:]))
        self.assertEqual(shape, self.test_fits_shape)

    def test_cropping(self):
        K = 0.5
        data = np.array([
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, K, K, K, K, 0, 0, 0],
            [0, 0, 0, K, K, K, K, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        ], dtype=np.float)
        buf = write_fits_image_file(data)
        buf.seek(0)
        # hdul = fits.open(buf)
        hdu, hdr = fits.getdata(buf, header=True)
        # For some reason (float errors?) the non-zero values are changed after
        # saving and reloading the FITS file. Get the 'new' K to compare the
        # cropped image with
        K2 = np.max(hdu)

        hdu,hdr = crop_image(hdu, hdr, scale=0.5)

        # Note that size of cropped image is not exactly half; it is off by one
        # due to rounding
        self.assertEqual(hdu.shape, (2, 4))
        self.assertTrue(np.all(hdu == np.full((2, 4), K2)), hdu)


class GalleryTestCase(TomEducationTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('tom_education:gallery')
        self.target = Target.objects.create(name='my target')
        self.prods = []

        image_data = np.ones((500, 4), dtype=np.float)
        image_data[20, :] = np.array([10, 20, 30, 40])
        for i in range(4):
            product_id = 'test{}'.format(i)
            prod = DataProduct.objects.create(
                product_id=product_id,
                target=self.target
            )
            buf = write_fits_image_file(image_data)
            prod.data.save(product_id, File(buf), save=True)
            self.prods.append(prod)
            setattr(self, 'pk{}'.format(i), str(prod.pk))

    def test_no_products(self):
        response = self.client.get(self.url)
        self.assertIn('messages', response.context)
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'No data products provided')
        self.assertNotIn('show_form', response.context)

    def test_context(self):
        pks = ','.join(map(str, [self.prods[0].pk, self.prods[2].pk]))
        response = self.client.get(self.url + '?product_pks={}'.format(pks))

        self.assertIn('form', response.context)
        form = response.context['form']
        self.assertTrue(isinstance(form, GalleryForm))
        self.assertEqual(form.product_pks, {str(self.prods[0].pk), str(self.prods[2].pk)})

        self.assertIn('product_pks', response.context)
        self.assertEqual(response.context['product_pks'], pks)
        self.assertIn('products', response.context)
        self.assertEqual(response.context['products'], {self.prods[0], self.prods[2]})

    def test_post(self):
        mygroup = DataProductGroup.objects.create(name='mygroup')

        response = self.client.post(self.url, {
            'product_pks': ','.join([str(p.pk) for p in self.prods]),
            'group': mygroup.pk,
            self.pk0: 'on',
            self.pk1: 'on',
        })

        # Products should have been added to the group
        for prod in self.prods[:2]:
            self.assertEqual(set(prod.group.all()), {mygroup})
        # Check no other products were added
        for prod in self.prods[2:]:
            self.assertEqual(set(prod.group.all()), set([]))

        # Should be redirected to group detail page
        self.assertEqual(response.status_code, 302)
        expected_url = '/dataproducts/data/group/{}/'.format(mygroup.pk)
        self.assertEqual(response.url, expected_url)
        # Check a success message is present
        response2 = self.client.get(expected_url)
        self.assertIn('messages', response2.context)
        messages = list(response2.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Added 2 data products to group \'mygroup\'')


class AsyncProcessTestCase(TomEducationTestCase):
    @patch('tom_education.models.async_process.datetime')
    def test_terminal_timestamp(self, dt_mock):
        somedate = datetime(
            year=2019, month=1, day=2, hour=3, minute=4, second=5, microsecond=6
        )
        dt_mock.now.return_value = somedate

        proc = AsyncProcess.objects.create(identifier='blah')
        self.assertTrue(proc.terminal_timestamp is None)

        # Timestamp should be set automatically when saving in a terminal state
        proc.status = ASYNC_STATUS_FAILED
        proc.save()
        self.assertEqual(proc.terminal_timestamp, somedate)


class AsyncStatusApiTestCase(TomEducationTestCase):
    @patch('django.utils.timezone.now')
    @patch('tom_education.models.async_process.datetime')
    @patch('tom_education.views.datetime')
    def test_api(self, views_dt_mock, models_dt_mock, django_mock):
        terminal_time = datetime(year=2019, month=1, day=2, hour=3, minute=4, second=5, microsecond=6)
        current_time = datetime(year=2050, month=1, day=1, hour=1, minute=1, second=1, microsecond=1)
        create_time1 = datetime(year=1970, month=1, day=1, hour=1, minute=1, second=1, microsecond=1)
        create_time2 = datetime(year=1971, month=1, day=1, hour=1, minute=1, second=1, microsecond=1)
        terminal_timestamp = terminal_time.timestamp()
        current_timestamp = current_time.timestamp()
        create_timestamp1 = create_time1.timestamp()
        create_timestamp2 = create_time2.timestamp()

        models_dt_mock.now.return_value = terminal_time
        views_dt_mock.now.return_value = current_time

        django_mock.return_value = create_time1
        target = Target.objects.create(name='my target')
        proc = AsyncProcess.objects.create(identifier='hello', target=target)
        # Make a failed process with a different creation time
        # Have it an PipelineProcess to check 'view_url' is provided
        django_mock.return_value = create_time2
        failed_proc = PipelineProcess.objects.create(
            identifier='ohno',
            target=target,
            status=ASYNC_STATUS_FAILED,
            failure_message='oops'
        )
        url = reverse('tom_education:async_process_status_api', kwargs={'target': target.pk})

        # Construct the dicts representing processes expected in the JSON
        # response (excluding fields that will change)
        proc_dict = {
            'process_type': 'AsyncProcess',
            'identifier': 'hello',
            'created': create_timestamp1,
            'terminal_timestamp': None,
            'view_url': None,
            'failure_message': None,
        }
        failed_proc_dict = {
            'process_type': 'PipelineProcess',
            'identifier': 'ohno',
            'created': create_timestamp2,
            'status': 'failed',
            'failure_message': 'oops',
            'terminal_timestamp': terminal_timestamp,
            'view_url': reverse('tom_education:pipeline_detail', kwargs={'pk': failed_proc.pk})
        }

        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response1.json(), {
            'timestamp': current_timestamp,
            'processes': [failed_proc_dict, dict(proc_dict, status='pending')]
        })

        proc.status = ASYNC_STATUS_CREATED
        proc.save()
        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json(), {
            'timestamp': current_timestamp,
            'processes': [
                failed_proc_dict,
                dict(proc_dict, status='created', terminal_timestamp=terminal_timestamp)
            ],
        })

        proc.status = ASYNC_STATUS_FAILED
        proc.save()
        response3 = self.client.get(url)
        self.assertEqual(response3.status_code, 200)
        self.assertEqual(response3.json(), {
            'timestamp': current_timestamp,
            'processes': [
                failed_proc_dict,
                dict(proc_dict, status='failed', terminal_timestamp=terminal_timestamp,
                     failure_message=None)
            ]
        })

        # Bad target PK should give 404
        response4 = self.client.get(reverse('tom_education:async_process_status_api', kwargs={'target': 100000}))
        self.assertEqual(response4.status_code, 404)
        self.assertEqual(response4.json(), {'detail': 'Not found.'})


class FakePipeline(PipelineProcess):
    short_name = 'fakepip'

    class Meta:
        proxy = True

    def do_pipeline(self, tmpdir, **kwargs):
        self.log("doing the thing")
        file1 = tmpdir / 'file1.csv'
        file2 = tmpdir / 'file2.hs'
        file3 = tmpdir / 'file3.png'
        file1.write_text('hello')
        file2.write_text('goodbye')
        file3.write_text('hello again')
        self.log("and another thing")
        return [
            (file1, DataProduct),
            (file2, ReducedDatum, 'image_file'),
            PipelineOutput(path=file3, output_type=DataProduct, data_product_type='image_file')
        ]


class FakePipelineWithFlags(FakePipeline):
    flags = {
        'myflag': {'default': False, 'long_name': 'myflag'},
        'default_true': {'default': True, 'long_name': 'Default True'},
        'default_false': {'default': False, 'long_name': 'Default False'},
    }

    class Meta:
        proxy = True
    # Create method to pass flags to, so we can mock it and check the correct
    # flags were passed

    def log_flags(self, flags):
        pass

    def do_pipeline(self, tmpdir, **flags):
        self.log_flags(flags)
        return super().do_pipeline(tmpdir)


class FakePipelineBadFlags(FakePipeline):
    flags = 4

    class Meta:
        proxy = True


class PipelineTestCase(TomEducationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        target_name = 't{}'.format(datetime.now().timestamp())
        cls.target = Target.objects.create(name=target_name)
        cls.prods = [DataProduct.objects.create(product_id=f'test_{i}', target=cls.target)
                     for i in range(4)]
        cls.pks = [str(prod.pk) for prod in cls.prods]
        for prod in cls.prods:
            fn = f'{prod.product_id}_file.tar.gz'
            prod.data.save(fn, File(BytesIO()))

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='test', email='test@example.com')
        self.client.force_login(self.user)
        assign_perm('tom_targets.view_target', self.user, self.target)

    def test_no_target(self):
        proc = FakePipeline.objects.create(identifier='notarget', target=None)
        proc.input_files.add(*self.prods)
        with self.assertRaises(AsyncError):
            proc.run()

    def test_no_input_files(self):
        proc = FakePipeline.objects.create(identifier='notarget', target=self.target)
        with self.assertRaises(AsyncError):
            proc.run()

    @patch('tom_education.models.pipelines.datetime')
    def test_save_outputs(self, dt_mock):
        dt_mock.now.return_value = datetime(
            year=1970, month=1, day=1, hour=0, minute=0, second=17
        )

        proc = FakePipeline.objects.create(identifier='someprocess', target=self.target)
        proc.input_files.add(*self.prods)
        proc.save()

        pre_dp_count = DataProduct.objects.count()
        pre_reduced_count = ReducedDatum.objects.count()
        pre_group_count = DataProductGroup.objects.count()
        self.assertEqual(pre_group_count, 0)

        proc.run()

        post_dp_count = DataProduct.objects.count()
        post_reduced_count = ReducedDatum.objects.count()
        post_group_count = DataProductGroup.objects.count()
        self.assertEqual(post_dp_count, pre_dp_count + 2)
        self.assertEqual(post_reduced_count, pre_reduced_count + 1)
        self.assertEqual(post_group_count, pre_group_count + 1)

        self.assertTrue(proc.group is not None)
        self.assertEqual(proc.group.name, 'someprocess_outputs')
        self.assertEqual(proc.group.dataproduct_set.count(), 2)

        # Output names and contents come from FakePipeline.do_pipeline
        file1_dp = DataProduct.objects.get(product_id='someprocess_file1.csv')
        file3_dp = DataProduct.objects.get(product_id='someprocess_file3.png')
        self.assertEqual(file1_dp.data.read(), b'hello')
        self.assertEqual(file3_dp.data.read(), b'hello again')

        self.assertEqual(file1_dp.data_product_type, '')
        self.assertEqual(file3_dp.data_product_type, 'image_file')

        file2_rd = ReducedDatum.objects.get(source_name='someprocess_file2.hs')
        self.assertEqual(file2_rd.target, self.target)
        self.assertEqual(file2_rd.data_type, 'image_file')
        self.assertEqual(file2_rd.timestamp.timestamp(), 17)
        self.assertEqual(file2_rd.value, 'goodbye')
        self.assertEqual(file2_rd.source_location, '')

    def _test_no_data_products(self):
        # **** This seems to have a problem because dataproduct is required **
        # If outputs are only reduced data, a data product group should not be
        # created
        class NoDataProductPipeline(PipelineProcess):
            class Meta:
                proxy = True

            def do_pipeline(pself, tmpdir):
                outfile = tmpdir / 'somefile.csv'
                outfile.write_text('this is a csv')
                return [(outfile, ReducedDatum)]

        pre_group_count = DataProductGroup.objects.count()
        pre_reduced_count = DataProductGroup.objects.count()

        proc = NoDataProductPipeline.objects.create(identifier='someprocess', target=self.target)
        proc.input_files.add(*self.prods)
        proc.save()
        proc.run()

        post_group_count = DataProductGroup.objects.count()
        post_reduced_count = ReducedDatum.objects.count()
        # No group should have been created
        self.assertEqual(post_group_count, pre_group_count)
        # ReducedDatum should still have been created
        self.assertEqual(post_reduced_count, pre_reduced_count + 1)

    def test_invalid_output_type(self):
        class InvalidOutputTypePipeline(PipelineProcess):
            class Meta:
                proxy = True

            def do_pipeline(pself, tmpdir):
                outfile = tmpdir / 'somefile.csv'
                outfile.write_text('this is a csv')
                return [(outfile, 'cheese', 'sometag')]

        proc = InvalidOutputTypePipeline.objects.create(identifier='someprocess', target=self.target)
        proc.input_files.add(*self.prods)
        proc.save()
        with self.assertRaises(AsyncError) as ex_info:
            proc.run()
        self.assertEqual("Invalid output type 'cheese'", str(ex_info.exception))

    def test_logs(self):
        proc = FakePipeline.objects.create(identifier='someprocess', target=self.target)
        proc.input_files.add(*self.prods)
        proc.save()
        proc.run()
        # Message comes from FakePipeline
        self.assertEqual(proc.logs, 'doing the thing\nand another thing\n')

    def test_update_status(self):
        class StatusTestPipeline(PipelineProcess):
            class Meta:
                proxy = True

            def do_pipeline(pself, tmpdir):
                with pself.update_status('doing something important'):
                    self.assertEqual(pself.status, 'doing something important')
                return []

        proc = StatusTestPipeline.objects.create(identifier='someprocess', target=self.target)
        proc.input_files.add(*self.prods)
        proc.save()
        proc.run()

    def test_view(self):
        proc_with_target = FakePipeline.objects.create(identifier='someprocess', target=self.target)
        url = reverse('tom_education:pipeline_detail', kwargs={'pk': proc_with_target.pk})
        target_url = reverse('tom_education:target_detail', kwargs={'pk': self.target.pk})
        response = self.client.get(url)
        self.assertIn('target_url', response.context)
        self.assertEqual(response.context['target_url'], target_url)

    @patch('django.utils.timezone.now')
    @patch('tom_education.models.async_process.datetime')
    def test_api(self, async_mock, django_mock):
        async_mock.now.return_value = datetime(
            year=1970, month=1, day=1, hour=0, minute=6, second=0, microsecond=0
        )
        django_mock.return_value = datetime(
            year=1970, month=1, day=1, hour=0, minute=5, second=0, microsecond=0
        )

        proc = FakePipeline.objects.create(
            target=self.target,
            identifier='someprocess',
            status='somestatus'
        )
        proc.input_files.add(*self.prods)
        proc.save()

        url = reverse('tom_education:pipeline_api', kwargs={'pk': proc.pk})
        view_url = reverse('tom_education:pipeline_detail', kwargs={'pk': proc.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'identifier': 'someprocess',
            'created': 300,
            'status': 'somestatus',
            'logs': '',
            'terminal_timestamp': None,
            'failure_message': None,
            'view_url': view_url,
            'group_name': None,
            'group_url': None,
        })

        proc.run()
        group_url = reverse('tom_dataproducts:group-detail', kwargs={'pk': proc.group.pk})
        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json(), {
            'identifier': 'someprocess',
            'created': 300,
            'status': ASYNC_STATUS_CREATED,
            'terminal_timestamp': 360,
            'failure_message': None,
            'view_url': view_url,
            'group_url': group_url,
            'group_name': 'someprocess_outputs',
            'logs': proc.logs
        })

        # Failure message should be included if process failed
        proc.status = ASYNC_STATUS_FAILED
        proc.failure_message = 'something went wrong'
        proc.save()
        response3 = self.client.get(url)
        self.assertEqual(response3.status_code, 200)
        self.assertEqual(response3.json(), {
            'identifier': 'someprocess',
            'created': 300,
            'status': ASYNC_STATUS_FAILED,
            'terminal_timestamp': 360,
            'failure_message': 'something went wrong',
            'view_url': view_url,
            'group_url': group_url,
            'group_name': 'someprocess_outputs',
            'logs': proc.logs
        })

        # Bad PK should give 404
        response4 = self.client.get(reverse('tom_education:pipeline_api', kwargs={'pk': 100000}))
        self.assertEqual(response4.status_code, 404)
        self.assertEqual(response4.json(), {'detail': 'Not found.'})

    @patch('tom_education.tests.FakePipelineWithFlags.log_flags')
    @patch('tom_education.models.pipelines.datetime')
    def test_form(self, dt_mock, flags_mock):
        """In the target data view"""
        url = reverse('tom_education:target_data', kwargs={'pk': self.target.pk})
        test_settings = {
            'mypip': 'tom_education.tests.FakePipeline',
            'withflags': 'tom_education.tests.FakePipelineWithFlags'
        }
        with self.settings(TOM_EDUCATION_PIPELINES=test_settings):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('pipeline_names', response.context)
            self.assertEqual(response.context['pipeline_names'], ['mypip', 'withflags'])
            self.assertIn('pipeline_flags', response.context)
            self.assertEqual(response.context['pipeline_flags'], {
                'withflags': FakePipelineWithFlags.flags
            })

            expect_400_data = [
                # missing pipeline name
                {'action': 'pipeline'},
                # invalid pipeline name
                {'action': 'pipeline', 'pipeline_name': 'blah'},
            ]
            for data in expect_400_data:
                resp = self.client.post(url, dict(data, **{self.pks[0]: 'on'}))
                self.assertEqual(resp.status_code, 400, data)

            # Give valid pipeline name and check it was created and run
            dt_mock.now.return_value = datetime(year=1980, month=1, day=1)
            response2 = self.client.post(url, {
                'action': 'pipeline', 'pipeline_name': 'mypip', self.pks[0]: 'on'
            })
            self.assertEqual(response2.status_code, 200)
            # Check process was made
            proc = PipelineProcess.objects.filter(identifier__startswith='fakepip').first()
            self.assertTrue(proc is not None)
            # Check outputs
            self.assertTrue(proc.group is not None)
            self.assertEqual(proc.group.dataproduct_set.count(), 2)
            # Shouldn't be any flags
            self.assertEqual(proc.flags_json, None)

            # POST with flags and check they were passed do the pipeline
            # correctly
            dt_mock.now.return_value = datetime(year=1981, month=1, day=1)
            response3 = self.client.post(url, {
                'action': 'pipeline', 'pipeline_name': 'withflags', self.pks[0]: 'on',
                'pipeline_flag_myflag': 'on',
                'pipeline_flag_default_false': 'on',
                'pipeline_flag_bogus': 'on',  # unexpected flag name should not cause problems
            })
            expected_flags = {'myflag': True, 'default_true': False, 'default_false': True}
            proc = PipelineProcess.objects.filter(identifier__contains='1981').get()
            self.assertEqual(proc.flags_json, json.dumps(expected_flags))
            flags_mock.assert_called_with(expected_flags)

    def test_invalid_pipelines(self):
        invalid_settings = [
            # Bad import paths
            {'mypip': 'blah'},
            {'mypip': 'fakepackage.blah'},
            {'mypip': 'tom_education.blah'},
            # Path to an object which is not a PipelineProcess subclass
            {'mypip': 'datetime.datetime'},
            # Class with invalid flags
            {'mypip': 'tom_education.tests.FakePipelineBadFlags'},
        ]

        url = reverse('tom_education:target_data', kwargs={'pk': self.target.pk})
        for invalid in invalid_settings:
            with self.settings(TOM_EDUCATION_PIPELINES=invalid):
                with self.assertRaises(InvalidPipelineError):
                    self.client.get(url)

    def test_validate_flags(self):
        invalid = [
            # Wrong type
            4, 'hello', [],
            # Missing default
            {'name': {'long_name': 'hello'}},
            # Missing long name
            {'name': {'default': False}},
            # Whitespace in name
            {'name with spaces': {'default': False, 'long_name': 'hello'}},
        ]
        for flags in invalid:
            with self.assertRaises(AssertionError):
                PipelineProcess.validate_flags(flags)

        # Should not raise an exception
        PipelineProcess.validate_flags(FakePipeline.flags)
        PipelineProcess.validate_flags(FakePipelineWithFlags.flags)

    def test_allowed_suffixes(self):
        tar_prod = DataProduct.objects.create(product_id='tar_prod', target=self.target)
        tar_prod.data.save('myarchive.tar', File(BytesIO()))

        proc = FakePipeline.objects.create(identifier='proc', target=self.target)
        proc.input_files.add(*self.prods, tar_prod)
        proc.save()

        with patch('tom_education.tests.FakePipeline.allowed_suffixes', ['.tar', '.7z']):
            with self.assertRaises(AsyncError) as ex_info:
                proc.run()
            err_msg = str(ex_info.exception)
            self.assertIn('_file.tar.gz', err_msg)  # filename of the offending file
            self.assertIn('.tar, .7z', err_msg)     # allowed suffixes

        with patch('tom_education.tests.FakePipeline.allowed_suffixes', ['.tar', '.tar.gz']):
            proc.run()


def mock_write_timelapse(_self, outfile, *args, **kwargs):
    pass


class TargetDetailApiTestCase(TomEducationTestCase):
    def setUp(self):
        super().setUp()
        write_timelapse_method = 'tom_education.models.timelapse.TimelapsePipeline.write_timelapse'

        now = datetime.now().timestamp()
        self.target_name = f'target_{now}'
        self.target = Target(
            name=self.target_name,
            ra=1.2345
        )
        self.target.save(extras={'extrafield': 'extravalue'})

        # Make some non-timelapse data products for the target
        data_products = [
            # (product_id, filename)
            ('fits1', 'somefile.fits'),
            ('fits2', 'somefile.fits.fz'),
            ('png', 'somefile.png'),
            ('no extension', 'randomfile'),
            ('not a real timelapse', 'timelapse.sh'),
        ]
        for product_id, filename in data_products:
            dp = DataProduct.objects.create(product_id=product_id, target=self.target)
            dp.data.save(filename, File(BytesIO()))

        # Make a non-timelapse pipeline process
        other_pipeline = PipelineProcess.objects.create(
            identifier='this_is_not_a_timelapse',
            target=self.target
        )
        other_pipeline.input_files.add(DataProduct.objects.first())
        other_pipeline.save()

        # Create GIF and WebM timelapses with 2 and 1 frames respectively
        dp1 = DataProduct.objects.create(product_id='dp1', target=self.target)
        dp2 = DataProduct.objects.create(product_id='dp2', target=self.target)
        dp1.data.save('frame1.fits.fz', File(BytesIO()))
        dp2.data.save('frame2.fits.fz', File(BytesIO()))

        tl_gif_pipeline = TimelapsePipeline.objects.create(
            identifier='gif_tl',
            target=self.target
        )
        tl_gif_pipeline.input_files.add(dp1, dp2)
        with patch(write_timelapse_method, mock_write_timelapse):
            with self.settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={'format': 'gif'}):
                tl_gif_pipeline.run()

        self.gif_creation = tl_gif_pipeline.terminal_timestamp
        self.gif_url = tl_gif_pipeline.group.dataproduct_set.first().data.url

        tl_webm_pipeline = TimelapsePipeline.objects.create(
            identifier='webm_tl',
            target=self.target
        )
        tl_webm_pipeline.input_files.add(dp1)
        with patch(write_timelapse_method, mock_write_timelapse):
            with self.settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={'format': 'webm'}):
                tl_webm_pipeline.run()

        self.webm_creation = tl_webm_pipeline.terminal_timestamp
        self.webm_url = tl_webm_pipeline.group.dataproduct_set.first().data.url

        # Make some timelapses pipelines in a non-terminal state: should not be
        # included in API response
        tl_failed = TimelapsePipeline.objects.create(
            identifier='tl_failed',
            target=self.target,
            status=ASYNC_STATUS_FAILED
        )
        tl_pending = TimelapsePipeline.objects.create(
            identifier='tl_pending',
            target=self.target,
            status=ASYNC_STATUS_PENDING
        )

    @override_settings(EXTRA_FIELDS=[{'name': 'extrafield', 'type': 'string'}])
    def test_api(self):
        self.maxDiff = None

        url = reverse('tom_education:target_api', kwargs={'pk': self.target.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'target': {
                'name': self.target_name,
                # Note: ra should be missing
                'extra_fields': {'extrafield': 'extravalue'},
            },
            # Should be sorted: most recent first
            'timelapses': [{
                'name': 'webm_tl_t.webm',
                'format': 'webm',
                'url': self.webm_url,
                'frames': 1,
                'created': self.webm_creation.timestamp()
            }, {
                'name': 'gif_tl_t.gif',
                'format': 'gif',
                'url': self.gif_url,
                'frames': 2,
                'created': self.gif_creation.timestamp()
            }]
        })

        url_404 = reverse('tom_education:target_api', kwargs={'pk': 1000000})
        response_404 = self.client.get(url_404)
        self.assertEqual(response_404.status_code, 404)
        self.assertEqual(response_404.json(), {'detail': 'Not found.'})


@override_settings(TOM_FACILITY_CLASSES=FAKE_FACILITIES)
@patch('tom_education.models.ObservationTemplate.get_identifier_field', return_value='test_input')
@patch('tom_education.views.TemplatedObservationCreateView.supported_facilities', ('TemplateFake',))
@patch('tom_education.views.ObservationAlertApiCreateView.throttle_scope', '')
class ObservationAlertApiTestCase(TomEducationTestCase):
    def setUp(self):
        super().setUp()
        self.target = Target.objects.create(name='my target')
        self.template = ObservationTemplate.objects.create(
            name='mytemplate',
            target=self.target,
            facility='TemplateFake',
            fields='{"test_input": "mytemplate", "extra_field": "somevalue", "another_extra_field": 17}'
        )

    @patch('tom_education.models.observation_template.datetime')
    def test_create(self, dt_mock, _mock):
        dt_mock.now.return_value = datetime(
            year=2019, month=1, day=2, hour=3, minute=4, second=5, microsecond=6
        )
        url = reverse('tom_education:observe_api')
        response = self.client.post(url, {
            'target': self.target.pk,
            'template_name': self.template.name,
            'facility': 'TemplateFake',
            'overrides': {'extra_field': 'hello'},
            'email': 'someone@somesite.org',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)

        # Check observation and alert were created
        self.assertEqual(ObservationRecord.objects.count(), 1)
        self.assertEqual(ObservationAlert.objects.count(), 1)

        ob = ObservationRecord.objects.first()
        alert = ObservationAlert.objects.first()

        self.assertEqual(ob.target, self.target)
        self.assertEqual(ob.facility, 'TemplateFake')
        self.assertEqual(json.loads(ob.parameters), {
            'target_id': self.target.pk,
            'facility': 'TemplateFake',
            'test_input': 'mytemplate-2019-01-02-030405',
            'extra_field': 'hello',
            'another_extra_field': 17,
            'observation_type': '',
        })

        self.assertEqual(alert.observation, ob)
        self.assertEqual(alert.email, 'someone@somesite.org')

    def test_no_overrides(self, _mock):
        url = reverse('tom_education:observe_api')
        response = self.client.post(url, {
            'target': self.target.pk,
            'template_name': self.template.name,
            'facility': 'TemplateFake',
            'email': 'someone@somesite.org',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ObservationAlert.objects.count(), 1)

    def test_invalid_target(self, _mock):
        url = reverse('tom_education:observe_api')
        response = self.client.post(url, {
            'target': 10000000000,
            'template_name': self.template.name,
            'facility': 'TemplateFake',
            'email': 'someone@somesite.org',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {
            'detail': 'Target not found.'
        })

    def test_invalid_facility(self, _mock):
        url = reverse('tom_education:observe_api')
        response = self.client.post(url, {
            'target': self.target.pk,
            'template_name': self.template.name,
            'facility': 'the facility you were looking for does not exist',
            'email': 'someone@somesite.org',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {
            'detail': 'Facility not found.'
        })

    def test_invalid_template(self, _mock):
        url = reverse('tom_education:observe_api')
        response = self.client.post(url, {
            'target': self.target.pk,
            'template_name': 'tempo',
            'facility': 'TemplateFake',
            'email': 'someone@somesite.org',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {
            'detail': "Template 'tempo' not found for target 'my target' and facility 'TemplateFake'"
        })

    def test_invalid_form(self, _mock):
        # Check that form validation is called, and that errors are passed back
        # in the API response
        url = reverse('tom_education:observe_api')
        response = self.client.post(url, {
            'target': self.target.pk,
            'template_name': self.template.name,
            'facility': 'TemplateFake',
            'email': 'someone@somesite.org',
            'overrides': {'another_extra_field': 'not an integer'},
        }, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {
            'another_extra_field': ['Enter a whole number.']
        })


@override_settings(TOM_FACILITY_CLASSES=FAKE_FACILITIES)
@patch('tom_education.tests.FakeTemplateFacility.save_data_products')
@patch('tom_education.models.TimelapsePipeline.write_timelapse', mock_write_timelapse)
@override_settings(TOM_EDUCATION_FROM_EMAIL_ADDRESS='tom@toolkit.edu')
class ProcessObservationAlertsTestCase(TomEducationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        target_ident = 'target_{}'.format(datetime.now().strftime('%s'))
        cls.target = Target.objects.create(name='my target')
        cls.ob = ObservingRecordFactory.create(
            target_id=cls.target.pk,
            facility=FakeTemplateFacility.name,
            status='not even started'
        )
        cls.dp1 = DataProduct.objects.create(product_id='dp1', target=cls.target)
        cls.dp2 = DataProduct.objects.create(product_id='dp2', target=cls.target)
        cls.dp3 = DataProduct.objects.create(product_id='dp3', target=cls.target)
        cls.dp1.data.save('img1.fits.fz', File(BytesIO()))
        cls.dp2.data.save('img2.fits.fz', File(BytesIO()))
        # Create a non-FITS file
        cls.dp3.data.save('img3.png', File(BytesIO()))

    def test_status_and_data_products_updated(self, save_dp_mock):
        alert = ObservationAlert.objects.create(observation=self.ob, email='someone@somesite.org')
        call_command('process_observation_alerts')
        save_dp_mock.assert_called_once_with(alert.observation)
        alert.refresh_from_db()
        self.assertEqual(alert.observation.status, 'COMPLETED')

    def test_non_alert_observation_not_updated(self, save_dp_mock):
        non_alert_ob = ObservingRecordFactory.create(
            target_id=self.target.pk,
            facility=FakeTemplateFacility.name,
            status='not even started'
        )
        call_command('process_observation_alerts')
        save_dp_mock.assert_not_called()
        non_alert_ob.refresh_from_db()
        self.assertEqual(non_alert_ob.status, 'not even started')

    @patch('tom_education.models.TimelapsePipeline.create_timestamped',
           wraps=TimelapsePipeline.create_timestamped)
    def test_timelapse_created(self, pipeline_mock, save_dp_mock):
        alert = ObservationAlert.objects.create(
            observation=self.ob, email='someone@somesite.org'
        )
        call_command('process_observation_alerts')
        self.assertEqual(TimelapsePipeline.objects.count(), 1)
        self.assertEqual(DataProduct.objects.filter(data_product_type=settings.DATA_PRODUCT_TYPES['timelapse'][0]).count(), 1)

        # Check method to create timelapse was called with the correct
        # arguments
        pipeline_mock.assert_called_once()
        args, _ = pipeline_mock.call_args
        self.assertEqual(len(args), 2)
        self.assertEqual(args[0], self.target)
        self.assertIsInstance(args[1], QuerySet)
        self.assertEqual(set(args[1].all()), {self.dp1, self.dp2})

    def test_old_timelapses_deleted(self, save_dp_mock):
        alert = ObservationAlert.objects.create(observation=self.ob, email='someone@somesite.org')
        tl = DataProduct.objects.create(
            target=self.target, product_id='mytimelapse', data_product_type=settings.DATA_PRODUCT_TYPES['timelapse'][0]
        )
        other_dp = DataProduct.objects.create(
            target=self.target, product_id='notatimelapse'
        )
        call_command('process_observation_alerts')
        # Old timelapse and its data should have been deleted
        self.assertEqual(DataProduct.objects.filter(pk=tl.pk).count(), 0)
        self.assertFalse(tl.data)
        # Other data product should not have been deleted
        self.assertEqual(DataProduct.objects.filter(pk=other_dp.pk).count(), 1)
        # Should be one (new) timelapse
        self.assertEqual(DataProduct.objects.filter(data_product_type=settings.DATA_PRODUCT_TYPES['timelapse'][0]).count(), 1)

    @patch('tom_education.models.TimelapsePipeline.create_timestamped',
           wraps=TimelapsePipeline.create_timestamped)
    def test_multiple_alerts_single_target(self, pipeline_mock, save_dp_mock):
        # Create two alerts for the same observation: the target should only
        # have one new timelapse created
        alert1 = ObservationAlert.objects.create(observation=self.ob, email='someone@somesite.org')
        alert2 = ObservationAlert.objects.create(observation=self.ob, email='someoneelse@somesite.org')
        call_command('process_observation_alerts')
        pipeline_mock.assert_called_once()

    @patch('tom_education.models.TimelapsePipeline.create_timestamped',
           wraps=TimelapsePipeline.create_timestamped)
    def test_exclude_raw_data(self, pipeline_mock, save_dp_mock):
        raw_dp = DataProduct.objects.create(product_id='raw', target=self.target)
        raw_dp.data.save('rawfile.e00.fits.fz', File(BytesIO()))
        alert = ObservationAlert.objects.create(observation=self.ob, email='someone@somesite.org')
        call_command('process_observation_alerts')

        pipeline_mock.assert_called_once()
        args, _ = pipeline_mock.call_args
        # Raw file should not be included
        self.assertEqual(set(args[1].all()), {self.dp1, self.dp2})

    def test_emails_sent(self, save_dp_mock):
        alert = ObservationAlert.objects.create(observation=self.ob, email='someone@somesite.org')
        call_command('process_observation_alerts')

        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['someone@somesite.org'])
        self.assertIn('Observation', msg.subject)
        self.assertIn('observation', msg.body)

    @override_settings()
    def test_no_from_email_address(self, save_dp_mock):
        # Unset from email add setting: should get an error message
        del settings.TOM_EDUCATION_FROM_EMAIL_ADDRESS
        alert = ObservationAlert.objects.create(observation=self.ob, email='someone@somesite.org')
        buf = StringIO()
        call_command('process_observation_alerts', stderr=buf)
        self.assertIn("TOM_EDUCATION_FROM_EMAIL_ADDRESS not set", buf.getvalue())


class DataProductDeleteMultipleViewTestCase(DataProductTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='test', email='test@example.com')
        self.client.force_login(self.user)
        assign_perm('tom_targets.view_target', self.user, self.target)
        self.url = reverse('tom_education:target_data', kwargs={'pk': self.target.pk})
        self.num_products = DataProduct.objects.count()

    def test_user_not_logged_in(self):
        self.client.logout()
        base_url = reverse('tom_education:delete_dataproducts')
        url = base_url + '?product_pks=' + ','.join(str(prod.pk) for prod in self.prods)
        response = self.client.get(url)
        # Should be redirected to login
        self.assertTrue(response.url.startswith(reverse('login') + '?'))
        # No DPs should have been deleted
        self.assertEqual(DataProduct.objects.count(), self.num_products)

        self.client.force_login(self.user)

    def test_confirmation_page(self):
        base_url = reverse('tom_education:delete_dataproducts')
        url = base_url + '?product_pks=' + ','.join(str(prod.pk) for prod in self.prods)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Check the filenames of the to-be-deleted products are displayed
        for prod in self.prods:
            self.assertIn(prod.data.name.encode(), response.content)
        # 'next' URL should be included in the form
        self.assertIn(b'<input type="hidden" name="next"', response.content)
        # Products should not have actually been deleted yet
        self.assertEqual(DataProduct.objects.count(), self.num_products)

    def test_delete(self):
        base_url = reverse('tom_education:delete_dataproducts')
        response = self.client.post(base_url, {
            'next': 'mycoolwebsite.net',
            'product_pks': ','.join(map(str, [self.prods[0].pk, self.prods[2].pk]))
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'mycoolwebsite.net')
        self.assertEqual(set(DataProduct.objects.all()), {self.prods[1], self.prods[3]})

        # Success message should be present on next page
        response2 = self.client.get('/')
        self.assertIn('messages', response2.context)
        messages = list(response2.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Deleted 2 data products')


def mock_instruments(_self):
    return {
        'myinstr': {
            'type': 'IMAGE',
            'class': '2M0',
            'name': 'test instrument',
            'optical_elements': {
                'filters': [
                    {'code': 'redfilter', 'name': 'RED', 'schedulable': True},
                    {'code': 'greenfilter', 'name': 'GREEN', 'schedulable': True},
                    {'code': 'bluefilter', 'name': 'BLUE', 'schedulable': True},
                ]
            }
        }
    }


def mock_proposals(_self):
    return [('myprop', 'some proposal')]


@patch('tom_education.facilities.EducationLCOForm._get_instruments', mock_instruments)
@patch('tom_education.facilities.EducationLCOForm.proposal_choices', mock_proposals)
@patch('tom_education.facilities.EducationLCOFacility.validate_observation', return_value=None)
@patch('tom_education.facilities.EducationLCOFacility.submit_observation', return_value=[1234])
class EducationLCOFacilityTestCase(TomEducationTestCase):
    def setUp(self):
        super().setUp()
        self.target = Target.objects.create(name='my target')
        self.url = reverse('tom_education:create_obs', kwargs={'facility': 'LCO'})
        self.user = User.objects.create_user(username='test', email='test@example.com')
        self.client.force_login(self.user)

        # Base form data excluding filter/exposure fields
        self.base_form_data = {
            'target_id': self.target.pk,
            'facility': 'LCO',
            'name': 'someobs',
            'proposal': 'myprop',
            'ipp_value': '1.05',
            'observation_mode': 'NORMAL',
            'max_airmass': '1.6',
            'start': '2000-01-01',
            'end': '2001-01-01',
            'instrument_type': 'myinstr'
        }

    def test_multiple_instrument_configurations(self, _validate_mock, submit_mock):
        response = self.client.post(self.url, data={
            **self.base_form_data,
            'redfilter_exposure_count': '1',
            'redfilter_exposure_time': '2',

            'bluefilter_exposure_count': '3',
            'bluefilter_exposure_time': '4',
        })
        # Check payload was submitted with correct-looking args
        submit_mock.assert_called_once()
        args, kwargs = submit_mock.call_args
        self.assertEqual(len(args), 1)
        self.assertEqual(kwargs, {})
        # Get submitted payload and check instrument configurations were
        # correct
        (payload,) = args
        configs = payload['requests'][0]['configurations']
        self.assertEqual(len(configs), 2)
        instr_configs = [config['instrument_configs'][0] for config in configs]
        red_instr_config = {
            'exposure_count': 1,
            'exposure_time': 2,
            'optical_elements': {'filter': 'redfilter'}
        }
        blue_instr_config = {
            'exposure_count': 3,
            'exposure_time': 4,
            'optical_elements': {'filter': 'bluefilter'}
        }
        self.assertIn(red_instr_config, instr_configs)
        self.assertIn(blue_instr_config, instr_configs)

    def test_exposure_settings(self, _validate_mock, submit_mock):
        # Check that we get an error if no filters are specified
        response = self.client.post(self.url, data=self.base_form_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].errors['__all__'], ['No filters selected'])

        # Check that we get an error if just time or just count are given
        response = self.client.post(self.url, data={
            **self.base_form_data,
            # Omit count for red
            'redfilter_exposure_time': '2',
            # Omit time for blue
            'bluefilter_exposure_count': '3',

            # Specify green properly
            'greenfilter_exposure_time': '20',
            'greenfilter_exposure_count': '19',
        })
        self.assertEqual(response.status_code, 200)
        expected_msgs = {
            "Exposure count missing for filter 'RED'",
            "Exposure time missing for filter 'BLUE'"
        }
        self.assertEqual(set(response.context['form'].errors['__all__']), expected_msgs)

    def test_instrument_filter_info(self, _validate_mock, _submit_mock):
        # Construct dict that looks like a response from the LCO instruments API
        instr_response = {
            'instr1': {
                'optical_elements': {
                    'filters': [
                        {'code': 'a1', 'schedulable': False},
                        {'code': 'a2', 'schedulable': True},
                    ],
                    'slits': [
                        {'code': 'a3', 'schedulable': True},
                    ]
                }
            },
            'instr2': {
                'optical_elements': {
                    'slits': [
                        {'code': 'b1', 'schedulable': True},
                    ]
                }
            }
        }
        expected = {
            'instr1': ['a2', 'a3'],
            'instr2': ['b1'],
        }
        got = EducationLCOForm.get_schedulable_codes(instr_response)
        self.assertEqual(got, expected)


class EducationTargetViewsTestCase(TomEducationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(username='test', email='test@example.com')
        cls.target = Target.objects.create(name='my target', type=Target.NON_SIDEREAL)
        assign_perm('tom_targets.change_target', cls.user, cls.target)

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    @override_settings(EXTRA_FIELDS=[{'name': 'strextra', 'type': 'string'},
                                     {'name': 'numericextra', 'type': 'number'}])
    def test_create_view(self):

        create_url = reverse('tom_education:target_create') + '?type={}'.format(Target.NON_SIDEREAL)
        update_url = reverse('tom_education:target_update', kwargs={'pk': self.target.pk})

        for url in (create_url, update_url):
            response = self.client.get(url)
            self.assertIn('non_sidereal_fields', response.context)
            field_info = json.loads(response.context['non_sidereal_fields'])
            self.assertEqual(set(field_info.keys()), {'base_fields', 'scheme_fields'})
            # Check declared, extra and core required fields are in base_fields
            self.assertTrue(
                {'groups', 'strextra', 'numericextra', 'scheme'} <= set(field_info['base_fields'])
            )
            self.assertIsInstance(field_info['scheme_fields'], dict)
