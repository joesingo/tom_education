from datetime import datetime
from io import BytesIO
import json
import os.path
from unittest.mock import patch

from astropy.io import fits
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import File
from django.db import transaction
from django.urls import reverse
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from guardian.shortcuts import assign_perm
import imageio
import numpy as np
from tom_dataproducts.models import DataProduct, IMAGE_FILE
from tom_targets.models import Target
from tom_observations.tests.factories import TargetFactory, ObservingRecordFactory
from tom_observations.tests.utils import FakeFacility, FakeFacilityForm

from tom_education.forms import TimelapseCreateForm
from tom_education.models import (
    ObservationTemplate, TimelapseDataProduct, DateFieldNotFoundError,
    TIMELAPSE_CREATED, TIMELAPSE_PENDING, TIMELAPSE_FAILED
)
from tom_education.tasks import make_timelapse


class FakeTemplateFacilityForm(FakeFacilityForm):
    # Add an extra field so we can check that the correct field is used as the
    # identifier
    extra_field = forms.CharField()


class FakeTemplateFacility(FakeFacility):
    name = 'TemplateFake'
    form = FakeTemplateFacilityForm


class AnotherFakeFacility(FakeFacility):
    name = 'AnotherFake'
    form = FakeTemplateFacilityForm


FAKE_FACILITIES = [
    'tom_education.tests.FakeTemplateFacility',
    'tom_education.tests.AnotherFakeFacility',
]


@override_settings(TOM_FACILITY_CLASSES=FAKE_FACILITIES)
@patch('tom_education.views.TemplatedObservationCreateView.get_identifier_field', return_value='test_input')
@patch('tom_education.views.TemplatedObservationCreateView.supported_facilities', ('TemplateFake',))
class ObservationTemplateTestCase(TestCase):
    facility = 'TemplateFake'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create(username='someuser', password='somepass', is_staff=True)
        cls.non_staff = User.objects.create(username='another', password='aaa')
        cls.target = Target.objects.create(identifier='mytarget', name='my target')

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
        target2 = Target.objects.create(identifier='anotherone', name='another')
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
            'target_id': self.target.pk,
            'facility': self.facility,
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

    def test_invalid_template_name(self, mock):
        template = ObservationTemplate.objects.create(
            name="cool-template-name",
            target=self.target,
            facility=self.facility,
            fields='...'
        )

        # The expected IntegrityError will break this test's DB transaction,
        # which prevents DB operations later on. Use atomic() to ensure changes
        # are rolled back
        with transaction.atomic():
            response = self.client.post(self.get_base_url(), {
                'test_input': 'cool-template-name',
                'extra_field': 'blah',
                'target_id': self.target.pk,
                'facility': self.facility,
                'create-template': 'yep'
            })
        self.assertEqual(response.status_code, 200)

        err_msg = 'Template name "cool-template-name" already in use'
        self.assertIn(err_msg, response.context['form'].errors['__all__'])

        # Double check that no template was created
        temp_count = ObservationTemplate.objects.all().count()
        self.assertEqual(temp_count, 1)

    @patch('tom_education.models.datetime')
    def test_instantiate_template(self, dt_mock, _):
        dt_mock.now.return_value = datetime(
            year=2019, month=1, day=2, hour=3, minute=4, second=5, microsecond=6
        )

        template = ObservationTemplate.objects.create(
            name='mytemplate',
            target=self.target,
            facility=self.facility,
            fields='{"test_input": "mytemplate", "extra_field": "someextravalue"}'
        )
        url = self.get_url(self.target) + '&template_id=' + str(template.pk)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        initial = response.context['form'].initial
        self.assertEqual(initial['test_input'], 'mytemplate-2019-01-02-030405')
        self.assertEqual(initial['extra_field'], 'someextravalue')


@override_settings(TOM_FACILITY_CLASSES=['tom_observations.tests.utils.FakeFacility'])
class TimelapseTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='test', email='test@example.com')
        self.client.force_login(self.user)
        assign_perm('tom_targets.view_target', self.user, self.target)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.target = TargetFactory.create()
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
        cls.image_data = np.ones((500, 4), dtype=np.float)
        cls.image_data[20, :] = np.array([10, 20, 30, 40])

        for i, date in enumerate(dates):
            primary_hdu = fits.PrimaryHDU()
            primary_hdu.header['XTENSION'] = 'IMAGE'
            primary_hdu.header['DATE-OBS'] = date.isoformat()
            # Create COMPRESSED image HDU, since this is the data we will need
            # to deal with
            img = fits.hdu.compressed.CompImageHDU(cls.image_data)

            hdul = fits.HDUList([primary_hdu, img])
            buf = BytesIO()
            hdul.writeto(buf)

            product_id = 'test{}'.format(i)
            prod = DataProduct.objects.create(
                product_id=product_id,
                target=cls.target,
                observation_record=cls.observation_record,
            )
            prod.data.save(product_id, File(buf), save=True)
            cls.prods.append(prod)

    def create_timelapse_dataproduct(self, products, **kwargs):
        tldp = TimelapseDataProduct.objects.create(
            product_id='test_{}'.format(datetime.now().isoformat()),
            target=self.target,
            observation_record=self.observation_record,
            **kwargs
        )
        tldp.frames.add(*products)
        tldp.save()
        return tldp

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

    @override_settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={'format': 'gif', 'fps': 16})
    @patch('tom_education.views.datetime')
    def test_create_timelapse_form(self, dt_mock):
        """
        Test the view and form, and check that the timelapse methods are called
        with the correct arguments
        """
        dt_mock.now.return_value = datetime(
            year=2019, month=1, day=2, hour=3, minute=4, second=5, microsecond=6
        )

        # GET page and check form is in the context
        url = reverse('tom_education:target_detail', kwargs={'pk': self.target.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('timelapse_form', response.context)
        self.assertIsInstance(response.context['timelapse_form'], TimelapseCreateForm)

        self.assertIn(b'Select all', response.content)
        self.assertIn(b'Select reduced', response.content)

        pre_tldp_count = TimelapseDataProduct.objects.count()
        self.assertEqual(pre_tldp_count, 0)

        # POST form
        response2 = self.client.post(url, {
            'test0': 'on',
            'test3': 'on',
            'test2': 'on',
        })
        # Should get JSON response
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json(), {'ok': True})

        # TimelapseDataProduct model should have been created
        post_tldp_count = TimelapseDataProduct.objects.count()
        self.assertEqual(post_tldp_count, pre_tldp_count + 1)
        tldp = TimelapseDataProduct.objects.all()[0]

        # Check the fields are correct
        self.assertEqual(tldp.target, self.target)
        self.assertEqual(tldp.observation_record, None)
        self.assertEqual(tldp.tag, IMAGE_FILE[0])
        expected_id = 'timelapse_{}_2019-01-02-030405'.format(self.target.identifier)
        expected_filename = expected_id + '.gif'
        self.assertEqual(tldp.product_id, expected_id)
        self.assertTrue(os.path.basename(tldp.data.name), expected_filename)
        self.assertEqual(set(tldp.frames.all()), {self.prods[0], self.prods[2], self.prods[3]})
        self.assertEqual(tldp.fmt, 'gif')
        self.assertEqual(tldp.fps, 16)

        # Status should be set
        self.assertTrue(tldp.status)

        # TODO: store format and FPS in the model and check their values here

    def test_timelapse_status_api(self):
        tl_prod = TimelapseDataProduct.objects.create(
            product_id='hello',
            target=self.target,
            status=TIMELAPSE_PENDING
        )
        failed_tl_prod = TimelapseDataProduct.objects.create(
            product_id='ohno',
            target=self.target,
            status=TIMELAPSE_FAILED,
            failure_message='oops'
        )
        url = reverse('tom_education:timelapse_status_api', kwargs={'target': self.target.pk})

        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response1.json(), {
            'ok': True,
            'timelapses': {
                'pending': [{'product_id': 'hello'}],
                'created': [],
                'failed': [{'product_id': 'ohno', 'failure_message': 'oops'}]
            }
        })

        tl_prod.status = TIMELAPSE_CREATED
        tl_prod.save()
        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json(), {
            'ok': True,
            'timelapses': {
                'pending': [],
                'created': [{'product_id': 'hello'}],
                'failed': [{'product_id': 'ohno', 'failure_message': 'oops'}]
            }
        })

        tl_prod.status = TIMELAPSE_FAILED
        tl_prod.save()
        response3 = self.client.get(url)
        self.assertEqual(response3.status_code, 200)
        self.assertEqual(response3.json(), {
            'ok': True,
            'timelapses': {
                'pending': [],
                'created': [],
                # When multiple timelapses in the same state, they should be
                # sorted by product ID
                'failed': [{'product_id': 'hello', 'failure_message': None},
                           {'product_id': 'ohno', 'failure_message': 'oops'}]
            }
        })

        # Bad target PK should give 404
        response4 = self.client.get(reverse('tom_education:timelapse_status_api', kwargs={'target': 100000}))
        self.assertEqual(response4.status_code, 404)
        self.assertEqual(response4.json(), {'ok': False, 'error': 'Target not found'})

    def test_empty_form(self):
        form = TimelapseCreateForm(target=self.target, data={})
        self.assertFalse(form.is_valid())

        form2 = TimelapseCreateForm(target=self.target, data={'test0': 'on'})
        self.assertTrue(form2.is_valid())

    def test_fits_file_sorting(self):
        correct_order = [self.prods[0], self.prods[1], self.prods[3], self.prods[2]]
        tldp = self.create_timelapse_dataproduct(self.prods)
        self.assertEqual(tldp.sorted_frames(), correct_order)

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
        tldp = self.create_timelapse_dataproduct([
            self.prods[0], self.prods[1], other_obs_prod
        ])
        tldp.write()
        tldp.save()

    def test_create_gif(self):
        tldp = self.create_timelapse_dataproduct(self.prods)
        buf = BytesIO()
        tldp._write(buf)
        self.assert_gif_data(buf)

        # Check the number of frames is correct
        buf.seek(0)
        frames = imageio.mimread(buf)
        self.assertEqual(len(frames), len(self.prods))
        # Check the size of the first frame
        self.assertEqual(frames[0].shape, self.image_data.shape)

        # TODO: check the actual image data

    def test_create_mp4(self):
        tldp = self.create_timelapse_dataproduct(self.prods, fmt='mp4')
        buf = BytesIO()
        tldp._write(buf)
        self.assert_mp4_data(buf)
        buf.seek(0)
        # Load and check the mp4 with imageio
        frames = imageio.mimread(buf, format='mp4')
        self.assertEqual(len(frames), len(self.prods))

    def test_create_webm(self):
        tldp = self.create_timelapse_dataproduct(self.prods, fmt='webm')
        buf = BytesIO()
        tldp._write(buf)
        buf.seek(0)
        self.assert_webm_data(buf)

    def test_invalid_fps(self):
        invalid_fpses = (0, -1)
        for fps in invalid_fpses:
            with self.assertRaises(ValidationError):
                TimelapseDataProduct.objects.create(
                    product_id=f'timelapse_fps_{fps}',
                    target=self.target,
                    observation_record=self.observation_record,
                    fps=fps
                )

    def test_write_to_data_attribute(self):
        tldp = self.create_timelapse_dataproduct(self.prods)
        tldp.product_id = 'myproductid'
        tldp.save()
        tldp.write()
        tldp.save()
        self.assertTrue(tldp.data.name.endswith('/myproductid.gif'))

        # Check the actual data file
        self.assert_gif_data(tldp.data.file)

    @patch('tom_education.models.TimelapseDataProduct.FITS_DATE_FIELD', new='hello')
    def test_no_observation_date_view(self):
        """
        Check we get the expected error when a FITS file does not contain the
        header for the date of the observation. This is achieved by patching
        the field name and setting it to 'hello'
        """
        tldp = self.create_timelapse_dataproduct(self.prods)
        with self.assertRaises(DateFieldNotFoundError):
            tldp.write()

    def test_make_timelapse_wrapper(self):
        tldp = self.create_timelapse_dataproduct(self.prods)
        # Cause an 'expected' error by patching date field: should get proper
        # failure message
        with patch('tom_education.models.TimelapseDataProduct.FITS_DATE_FIELD', new='hello') as _mock:
            make_timelapse(tldp.pk)
            tldp.refresh_from_db()
            self.assertEqual(tldp.status, TIMELAPSE_FAILED)
            self.assertTrue(isinstance(tldp.failure_message, str))
            self.assertTrue(tldp.failure_message.startswith('Could not find observation date'))

        # Cause an 'unexpected' error: should get generic failure message
        tldp2 = self.create_timelapse_dataproduct(self.prods)
        with patch('tom_education.models.imageio', new='hello') as _mock:
            make_timelapse(tldp2.pk)
            tldp2.refresh_from_db()
            self.assertEqual(tldp2.status, TIMELAPSE_FAILED)
            self.assertTrue(isinstance(tldp2.failure_message, str))
            self.assertEqual(tldp2.failure_message, 'An unexpected error occurred')
