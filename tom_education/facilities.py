import json
import requests
from django.conf import settings
from django.core.files.base import ContentFile

from crispy_forms.layout import Div
from dateutil.parser import parse
from tom_observations.facilities.lco import LCOFacility, LCOImagingObservationForm, make_request, PORTAL_URL

try:
    AUTO_THUMBNAILS = settings.AUTO_THUMBNAILS
except AttributeError:
    AUTO_THUMBNAILS = False

class EducationLCOForm(LCOImagingObservationForm):
    @staticmethod
    def get_schedulable_codes(api_response):
        """
        For a JSON response from the instruments API, return a dictionary
        mapping instrument names to lists of filter/slit codes which are
        schedulable
        """
        info = {}
        for name, val in api_response.items():
            keys = ('filters', 'slits')
            for key in keys:
                objs = val['optical_elements'].get(key, [])
                allowed = [obj['code'] for obj in objs if obj['schedulable']]
                if name not in info:
                    info[name] = []
                info[name] += allowed
        return info

    def get_extra_context(self):
        """
        Provide extra context to the view using this form.
        """
        json_response = make_request('GET', PORTAL_URL + '/api/instruments/').json()
        info = EducationLCOForm.get_schedulable_codes(json_response)
        return {'instrument_filters': json.dumps(info)}

    def layout(self):
        """
        Override default layout to swap the order of 'filter' and
        'instrument_type'
        """
        return Div(
            Div(
                'name', 'proposal', 'ipp_value', 'observation_mode', 'start', 'end',
                css_class='col'
            ),
            Div(
                'instrument_type', 'filter', 'exposure_count', 'exposure_time', 'max_airmass',
                css_class='col'
            ),
            css_class='form-row'
        )

class EducationLCOFacility(LCOFacility):
    def get_form(self, *args):
        return EducationLCOForm

    def data_products(self, observation_id, product_id=None):
        """
        Override this method to include reduction level in the dict for each
        data product
        """
        products = []
        for frame in self._archive_frames(observation_id, product_id):
            extra =  {'date_obs': frame['DATE_OBS'],
                 'instrument': frame['INSTRUME'],
                 'siteid': frame['SITEID'],
                 'telid': frame['TELID'],
                 'exp_time': frame['EXPTIME'],
                 'filter': frame['FILTER']
            }
            products.append({
                'id': frame['id'],
                'filename': frame['filename'],
                'created': parse(frame['DATE_OBS']),
                'url': frame['url'],
                'reduced': frame['RLEVEL'] == 91,
                'extra' : extra
            })
        return products

    def save_data_products(self, observation_record, product_id=None):
        from tom_dataproducts.models import DataProduct
        from tom_dataproducts.utils import create_image_dataproduct
        final_products = []
        products = self.data_products(observation_record.observation_id, product_id)
        for product in products:
            dp, created = DataProduct.objects.get_or_create(
                product_id=product['id'],
                target=observation_record.target,
                observation_record=observation_record,
                extra_data = json.dumps(product['extra'])
            )
            if created:
                product_data = requests.get(product['url']).content
                dfile = ContentFile(product_data)
                dp.data.save(product['filename'], dfile)
                dp.save()
                dp.get_preview()
            if AUTO_THUMBNAILS:
                create_image_dataproduct(dp)
            final_products.append(dp)
        return final_products
