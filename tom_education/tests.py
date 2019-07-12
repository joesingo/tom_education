from datetime import datetime
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
from unittest.mock import patch

from astropy.io import fits
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import File
from django.core.management import call_command
from django.db import transaction
from django.urls import reverse
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from guardian.shortcuts import assign_perm
import imageio
import numpy as np
from tom_dataproducts.models import DataProduct, DataProductGroup, IMAGE_FILE
from tom_targets.models import Target
from tom_observations.tests.factories import ObservingRecordFactory
from tom_observations.tests.utils import FakeFacility, FakeFacilityForm

from tom_education.forms import DataProductActionForm, GalleryForm
from tom_education.models import (
    AutovarProcess, AsyncError, AsyncProcess, ObservationTemplate,
    TimelapseDataProduct, TimelapseProcess, DateFieldNotFoundError,
    ASYNC_STATUS_CREATED, ASYNC_STATUS_PENDING, ASYNC_STATUS_FAILED
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
        cls.target = Target.objects.create(identifier='target123', name='my target')

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

        cls.target = Target.objects.create(identifier='target123', name='my target')
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
            product_id = 'test{}'.format(i)
            prod = DataProduct.objects.create(
                product_id=product_id,
                target=cls.target,
                observation_record=cls.observation_record,
            )
            buf = write_fits_image_file(cls.image_data, date)
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
    @patch('tom_education.models.datetime')
    def test_create_timelapse_form(self, dt_mock):
        """
        Test the view and form, and check that the timelapse is created
        successfully
        """
        dt_mock.now.return_value = datetime(
            year=2019, month=1, day=2, hour=3, minute=4, second=5, microsecond=6
        )

        # GET page and check form is in the context
        url = reverse('tom_education:target_detail', kwargs={'pk': self.target.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('dataproducts_form', response.context)
        self.assertIsInstance(response.context['dataproducts_form'], DataProductActionForm)

        self.assertIn(b'Select all', response.content)
        self.assertIn(b'Select reduced', response.content)

        pre_tldp_count = TimelapseDataProduct.objects.count()
        self.assertEqual(pre_tldp_count, 0)

        # POST form
        response2 = self.client.post(url, {
            'action': 'create_timelapse',
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

    def test_empty_form(self):
        form = DataProductActionForm(target=self.target, data={})
        self.assertFalse(form.is_valid())

        form2 = DataProductActionForm(target=self.target, data={'action': 'blah'})
        self.assertFalse(form2.is_valid())

        form3 = DataProductActionForm(target=self.target, data={'test0': 'on', 'action': 'blah'})
        self.assertTrue(form3.is_valid())

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
        tldp.product_id = 'myproductid_{}'.format(datetime.now().strftime('%s'))
        tldp.save()
        tldp.write()
        tldp.save()
        exp_filename = '/' + tldp.product_id + '.gif'
        self.assertTrue(tldp.data.name.endswith(exp_filename), tldp.data.name)

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
            make_timelapse(tldp)
            # process should have been created
            process = TimelapseProcess.objects.filter(
                identifier=tldp.get_filename(),
                target=tldp.target,
                timelapse_product=tldp
            ).first()
            self.assertTrue(process is not None)
            self.assertEqual(process.status, ASYNC_STATUS_FAILED)
            self.assertTrue(isinstance(process.failure_message, str))
            self.assertTrue(process.failure_message.startswith('Could not find observation date'))

        # Cause an 'unexpected' error: should get generic failure message
        tldp2 = self.create_timelapse_dataproduct(self.prods)
        with patch('tom_education.models.imageio', new='hello') as _mock:
            make_timelapse(tldp2.pk)
            process2 = TimelapseProcess.objects.get(identifier=tldp2.get_filename())
            self.assertEqual(process2.status, ASYNC_STATUS_FAILED)
            self.assertTrue(isinstance(process2.failure_message, str))
            self.assertEqual(process2.failure_message, 'An unexpected error occurred')

    @override_settings(TOM_EDUCATION_TIMELAPSE_SETTINGS={'format': 'gif', 'fps': 16},
                       TOM_EDUCATION_TIMELAPSE_GROUP_NAME='timelapsey')
    def test_management_command(self):
        pre_tldp_count = TimelapseDataProduct.objects.count()
        self.assertEqual(pre_tldp_count, 0)

        # Make first 3 products in timelapse group, but have the third one a
        # raw file
        group = DataProductGroup.objects.create(name='timelapsey')
        for prod in self.prods[:3]:
            prod.group.add(group)
            prod.save()
        rawfilename = 'somerawfile_{}.e91.fits.fz'.format(datetime.now().strftime('%s'))
        self.prods[2].data.save(rawfilename, File(BytesIO()), save=True)

        # Make a product in the group but for a different target: it should
        # not be included in the timelapse
        other_target = Target.objects.create(identifier='someothertarget')
        other_prod = DataProduct.objects.create(product_id='someotherproduct', target=other_target)
        other_prod.group.add(group)
        other_prod.save()

        buf = StringIO()
        call_command('create_timelapse', self.target.pk, stdout=buf)

        # Check timelapse object created
        post_tldp_count = TimelapseDataProduct.objects.count()
        self.assertEqual(post_tldp_count, pre_tldp_count + 1)

        # Check the timelapse itself
        tldp = TimelapseDataProduct.objects.all()[0]
        self.assertEqual(tldp.target, self.target)
        self.assertEqual(set(tldp.frames.all()), set(self.prods[:2]))
        self.assert_gif_data(tldp.data.file)

        # Check the command output
        output = buf.getvalue()
        self.assertTrue('Creating timelapse of 2 files for target target123 (my target)...' in output)
        self.assertTrue('Created timelapse' in output)

    def test_management_command_no_dataproducts(self):
        buf = StringIO()
        call_command('create_timelapse', self.target.pk, stdout=buf)
        output = buf.getvalue()
        self.assertTrue('Nothing to do' in output, 'Output was: {}'.format(output))
        self.assertEqual(TimelapseDataProduct.objects.count(), 0)
        # The timelapse group should have been created
        self.assertEqual(DataProductGroup.objects.count(), 1)

    def test_dataproduct_table(self):
        """
        Check that only created timelapses are shown in the data product table
        in the target detail view
        """
        # Create one timelapse for each status
        pending = TimelapseDataProduct.objects.create(product_id='pend', target=self.target)
        created = TimelapseDataProduct.objects.create(product_id='cre', target=self.target)
        failed = TimelapseDataProduct.objects.create(product_id='fail', target=self.target)
        TimelapseProcess.objects.create(
            identifier='pend', status=ASYNC_STATUS_PENDING, timelapse_product=pending
        )
        TimelapseProcess.objects.create(
            identifier='cre', status=ASYNC_STATUS_CREATED, timelapse_product=created
        )
        TimelapseProcess.objects.create(
            identifier='fail', status=ASYNC_STATUS_FAILED, timelapse_product=failed
        )

        url = reverse('tom_education:target_detail', kwargs={'pk': self.target.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        expected = self.prods + [created]
        unexpected = [pending, failed]
        for prod in expected:
            filename = prod.get_file_name()
            self.assertIn(filename, response.content.decode(), filename)
        for prod in unexpected:
            filename = prod.get_file_name()
            self.assertNotIn(filename, response.content.decode(), filename)


class GalleryTestCase(TestCase):
    def setUp(self):
        super().setUpClass()
        self.url = reverse('tom_education:gallery')
        self.target = Target.objects.create(identifier='target123', name='my target')
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
        self.assertEqual(form.product_ids, {self.prods[0].product_id, self.prods[2].product_id})

        self.assertIn('product_pks', response.context)
        self.assertEqual(response.context['product_pks'], pks)
        self.assertIn('products', response.context)
        self.assertEqual(response.context['products'], {self.prods[0], self.prods[2]})

    def test_post(self):
        mygroup = DataProductGroup.objects.create(name='mygroup')

        response = self.client.post(self.url, {
            'product_pks': ','.join([str(p.pk) for p in self.prods]),
            'group': mygroup.pk,
            'test0': 'on',
            'test1': 'on',
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


class AsyncProcessTestCase(TestCase):
    @patch('tom_education.models.datetime')
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


class AsyncStatusApiTestCase(TestCase):
    @patch('django.utils.timezone.now')
    @patch('tom_education.models.datetime')
    @patch('tom_education.views.datetime')
    def test_api(self, views_dt_mock, models_dt_mock, django_mock):
        d1 = datetime(year=2019, month=1, day=2, hour=3, minute=4, second=5, microsecond=6)
        d2 = datetime(year=2050, month=1, day=1, hour=1, minute=1, second=1, microsecond=1)
        d3 = datetime(year=1970, month=1, day=1, hour=1, minute=1, second=1, microsecond=1)
        timestamp1 = d1.timestamp()
        timestamp2 = d2.timestamp()
        timestamp3 = d3.timestamp()

        models_dt_mock.now.return_value = d1
        views_dt_mock.now.return_value = d2
        django_mock.return_value = d3

        target = Target.objects.create(identifier='target123', name='my target')
        proc = AsyncProcess.objects.create(
            identifier='hello',
            target=target,
            status=ASYNC_STATUS_PENDING,
        )
        failed_proc = AsyncProcess.objects.create(
            identifier='ohno',
            target=target,
            status=ASYNC_STATUS_FAILED,
            failure_message='oops'
        )
        url = reverse('tom_education:async_process_status_api', kwargs={'target': target.pk})

        # Construct the dicts representing processes expected in the JSON
        # response
        proc_dict = {
            'identifier': 'hello',
            'created': timestamp3
        }
        failed_proc_dict = {
            'identifier': 'ohno',
            'created': timestamp3,
            'failure_message': 'oops',
            'terminal_timestamp': timestamp1
        }

        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response1.json(), {
            'ok': True,
            'timestamp': timestamp2,
            'processes': {'pending': [proc_dict], 'created': [], 'failed': [failed_proc_dict]}
        })

        proc.status = ASYNC_STATUS_CREATED
        proc.save()
        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json(), {
            'ok': True,
            'timestamp': timestamp2,
            'processes': {
                'pending': [],
                'created': [dict(proc_dict, terminal_timestamp=timestamp1)],
                'failed': [failed_proc_dict]
            }
        })

        proc.status = ASYNC_STATUS_FAILED
        proc.save()
        response3 = self.client.get(url)
        self.assertEqual(response3.status_code, 200)
        self.assertEqual(response3.json(), {
            'ok': True,
            'timestamp': timestamp2,
            'processes': {
                'pending': [], 'created': [],
                # When multiple processes in the same state, they should be
                # sorted by product ID ('hello' and 'ohno' in this case)
                'failed': [
                    dict(proc_dict, failure_message=None, terminal_timestamp=timestamp1),
                    failed_proc_dict
                ]
            }
        })

        # Bad target PK should give 404
        response4 = self.client.get(reverse('tom_education:async_process_status_api', kwargs={'target': 100000}))
        self.assertEqual(response4.status_code, 404)
        self.assertEqual(response4.json(), {'ok': False, 'error': 'Target not found'})


def mock_do_autovar(_self, avdir):
    print("doing the thing")
    one = avdir / 'one'
    one.mkdir()
    (one / 'file1.csv').write_text('hello')
    (one / 'file2.png').write_text('goodbye')


@patch('tom_education.models.AutovarProcess.do_autovar', mock_do_autovar)
class AutovarTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        target_identifier = 'mytarget_{}'.format(datetime.now().timestamp())
        cls.target = Target.objects.create(identifier=target_identifier, name='my target')
        cls.prods = [DataProduct.objects.create(product_id=f'test_{i}', target=cls.target)
                     for i in range(4)]
        for prod in cls.prods:
            fn = f'{prod.product_id}_file'
            prod.data.save(fn, File(BytesIO()))

    def test_no_target(self):
        proc = AutovarProcess.objects.create(identifier='notarget', target=None)
        proc.input_files.add(*self.prods)
        with self.assertRaises(AsyncError):
            proc.run()

    def test_no_input_files(self):
        proc = AutovarProcess.objects.create(identifier='notarget', target=self.target)
        with self.assertRaises(AsyncError):
            proc.run()

    def test_tmpdir_creation(self):
        proc = AutovarProcess.objects.create(identifier='someprocess', target=self.target)
        proc.input_files.add(*self.prods)
        proc.save()

        with proc.autovar_dir() as avdir:
            self.assertTrue(isinstance(avdir, Path))
            listing = {p.name for p in avdir.iterdir()}
            self.assertEqual(listing, {
                'test_0_file', 'test_1_file', 'test_2_file', 'test_3_file'
            })

    def test_tmpdir_cleanup(self):
        """
        Check that the temporary dir is deleted after processing, even in the
        case of an error
        """
        proc = AutovarProcess.objects.create(identifier='someprocess', target=self.target)
        proc.input_files.add(*self.prods)
        proc.save()

        path1 = None
        path2 = None
        with proc.autovar_dir() as avdir:
            path1 = Path(avdir.absolute())
        try:
            with proc.autovar_dir() as avdir:
                path2 = Path(avdir.absolute())
                raise AsyncError('blah')
        except AsyncError:
            pass

        self.assertFalse(path1.exists())
        self.assertFalse(path2.exists())

    @patch('tom_education.models.AutovarProcess.output_dirs', ['one', 'two', 'nonexistant'])
    def test_gather_outputs(self):
        proc = AutovarProcess.objects.create(identifier='someprocess', target=self.target)
        proc.input_files.add(*self.prods)
        proc.save()

        with proc.autovar_dir() as avdir:
            one = avdir / 'one'
            one_subdir = one / 'subdir'
            two = avdir / 'two'
            three = avdir / 'three'
            one.mkdir()
            one_subdir.mkdir()
            two.mkdir()
            three.mkdir()

            file1 = one / 'file1.png'
            file2 = one / 'file2.bmp'
            file3 = two / 'file3.tar.gz'
            file4 = three / 'file4.txt'

            file1.write_text('hello')
            file2.write_text('hello')
            file3.write_text('hello')
            file4.write_text('hello')

            outputs = set(proc.gather_outputs(avdir))
            self.assertEqual(outputs, {file1, file2, file3})

    @patch('tom_education.models.AutovarProcess.output_dirs', ['one'])
    def test_create_group(self):
        proc = AutovarProcess.objects.create(identifier='someprocess', target=self.target)
        proc.input_files.add(*self.prods)
        proc.save()

        pre_dp_count = DataProduct.objects.count()
        pre_group_count = DataProductGroup.objects.count()
        self.assertEqual(pre_group_count, 0)

        proc.run()

        post_dp_count = DataProduct.objects.count()
        post_group_count = DataProductGroup.objects.count()
        self.assertEqual(post_dp_count, pre_dp_count + 2)
        self.assertEqual(post_group_count, pre_group_count + 1)

        group = DataProductGroup.objects.first()
        self.assertEqual(group.name, 'someprocess_outputs')
        self.assertEqual(group.dataproduct_set.count(), 2)

        file1_dp = DataProduct.objects.get(product_id='someprocess_file1.csv')
        file2_dp = DataProduct.objects.get(product_id='someprocess_file2.png')

        self.assertEqual(file1_dp.data.read(), b'hello')
        self.assertEqual(file2_dp.data.read(), b'goodbye')
