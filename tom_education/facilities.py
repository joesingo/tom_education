import json

from crispy_forms.layout import Div
from dateutil.parser import parse
from tom_observations.facilities.lco import LCOFacility, LCOImagingObservationForm, make_request, PORTAL_URL

class EducationLCOForm(LCOImagingObservationForm):
    def get_extra_context(self):
        """
        Provide extra context to the view using this form.

        Gets instrument information from the LCO API and constructs a list of
        available filters/slits for each instrument.
        """
        json_response = make_request('GET', PORTAL_URL + '/api/instruments/').json()
        info = {}
        for name, val in json_response.items():
            keys = ('filters', 'slits')
            for key in keys:
                objs = val['optical_elements'].get(key, [])
                allowed = [obj['code'] for obj in objs if obj['schedulable']]
                if name not in info:
                    info[name] = []
                info[name] += allowed

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
            products.append({
                'id': frame['id'],
                'filename': frame['filename'],
                'created': parse(frame['DATE_OBS']),
                'url': frame['url'],
                'reduced': frame['RLEVEL'] == 91
            })
        return products
