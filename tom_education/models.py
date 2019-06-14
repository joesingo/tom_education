from urllib.parse import urlparse, parse_qs, urlunparse

from django.db import models
from django.utils.http import urlencode
from tom_targets.models import Target


class ObservationTemplate(models.Model):
    name = models.CharField(max_length=255, null=False)
    target = models.ForeignKey(Target, on_delete='cascade', null=False)
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
