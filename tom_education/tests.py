"""
TODO:
check date appended to identifier when instantiating template
error message for creating template with same name
"""
import json
from unittest.mock import patch

from django.urls import reverse
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from tom_targets.models import Target

from tom_education.models import ObservationTemplate


@override_settings(TOM_FACILITY_CLASSES=['tom_observations.tests.utils.FakeFacility'])
class ObservationTemplateTestCase(TestCase):
    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.user = User.objects.create(username='someuser', password='somepass', is_staff=True)
        self.non_staff = User.objects.create(username='another', password='aaa')
        self.target = Target.objects.create(identifier='mytarget', name='my target')
        self.create_url = reverse('tom_education:create_obs', kwargs={'facility': 'FakeFacility'})

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def get_url(self, target):
        return '{}?target_id={}'.format(self.create_url, target.pk)

    def test_existing_templates_shown(self):
        template = ObservationTemplate.objects.create(
            name='mytemplate',
            target=self.target,
            facility='FakeFacility',
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

    def test_create_button(self):
        response = self.client.get(self.get_url(self.target))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'create-template', response.content)
        self.assertIn(b'Create new template', response.content)

        # Should not be present as non-staff
        self.client.force_login(self.non_staff)
        response2 = self.client.get(self.get_url(self.target))
        self.assertEqual(response2.status_code, 200)
        self.assertNotIn(b'create-template', response2.content)
        self.assertNotIn(b'Create new template', response2.content)

    @patch('tom_education.views.TemplatedObservationCreateView.get_identifier_field', return_value='test_input')
    def test_create_template(self, mock):
        self.assertEqual(ObservationTemplate.objects.all().count(), 0)
        fields = {
            'test_input': 'some-name',
            'target_id': self.target.pk,
            'facility': 'FakeFacility',
        }
        post_params = dict(fields, **{
            'create-template': 'yes please'
        })

        # Should not be able to POST as non-staff user
        self.client.force_login(self.non_staff)
        response = self.client.post(self.create_url, post_params)
        self.assertEqual(response.status_code, 403)

        # Test as staff user
        self.client.force_login(self.user)
        response2 = self.client.post(self.create_url, post_params)
        self.assertEqual(response2.status_code, 302)
        self.assertEqual(response2.url, self.get_url(self.target) + '&template_id=1')

        # ObservationTemplate object should have been created
        self.assertEqual(ObservationTemplate.objects.all().count(), 1)
        template = ObservationTemplate.objects.all()[0]
        self.assertEqual(template.name, 'some-name')
        self.assertEqual(template.target, self.target)
        self.assertEqual(template.facility, 'FakeFacility')
        self.assertEqual(json.loads(template.fields), fields)
