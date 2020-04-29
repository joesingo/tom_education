import os.path

from django.shortcuts import reverse
from django.contrib.sites.shortcuts import get_current_site
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers
from tom_targets.models import Target
from tom_dataproducts.models import DataProduct

from tom_education.models import AsyncProcess, PipelineProcess


class TimestampField(serializers.Field):
    def to_representation(self, dt):
        return dt.timestamp()


class AsyncProcessSerializer(serializers.ModelSerializer):
    created = TimestampField()
    terminal_timestamp = TimestampField()
    failure_message = serializers.SerializerMethodField()
    view_url = serializers.SerializerMethodField()

    class Meta:
        model = AsyncProcess
        fields = [
            'identifier', 'created', 'status', 'terminal_timestamp', 'failure_message', 'view_url',
            'process_type'
        ]

    def get_view_url(self, obj):
        """
        Special case for PipelineProcess objects: provide link to detail view
        """
        if hasattr(obj, 'pipelineprocess'):
            return reverse('tom_education:pipeline_detail', kwargs={'pk': obj.pk})
        return None

    def get_failure_message(self, obj):
        return obj.failure_message or None


class PipelineProcessSerializer(AsyncProcessSerializer):
    group_name = serializers.SerializerMethodField()
    group_url = serializers.SerializerMethodField()
    logs = serializers.SerializerMethodField()

    class Meta:
        model = PipelineProcess
        fields = [
            'identifier', 'created', 'status', 'terminal_timestamp', 'failure_message', 'view_url',
            'logs', 'group_name', 'group_url'
        ]

    def get_group_name(self, obj):
        if obj.group:
            return obj.group.name
        return None

    def get_group_url(self, obj):
        if obj.group:
            return reverse('tom_dataproducts:group-detail', kwargs={'pk': obj.group.pk})
        return None

    def get_logs(self, obj):
        """
        Make sure logs is always a string
        """
        return obj.logs or ''


class TargetSerializer(serializers.ModelSerializer):
    """
    Serialize a subset of the Target fields, plus any extra fields
    """
    class Meta:
        model = Target
        fields = ['name', 'extra_fields']

class PhotometrySerializer(serializers.Serializer):
    """
    Serializer for photometry data file URL and image
    """
    csv = serializers.SerializerMethodField()
    plot = serializers.SerializerMethodField()

    def get_csv(self, obj):
        url = reverse('tom_education:photometry_download', kwargs={'pk':obj.id})
        connection_type = 'https'
        if settings.DEBUG:
            connection_type = 'http'
        request = self.context.get("request")
        full_url = f"{connection_type}://{get_current_site(request)}{url}"
        return full_url

    def get_plot(self, obj):
        try:
            dp = DataProduct.objects.filter(target=obj, data_product_type='plot').latest('created')
            return dp.data.url
        except ObjectDoesNotExist:
            return None


class TimelapsePipelineSerializer(serializers.Serializer):
    """
    Serialize basic info for a timelapse from a TimelapsePipeline object,
    including the (relative) URL to the actual timelapse file
    """
    name = serializers.SerializerMethodField()
    format = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    created = serializers.SerializerMethodField()
    frames = serializers.SerializerMethodField()

    def _get_dataproduct(self, obj):
        return obj.group.dataproduct_set.first()

    def get_name(self, obj):
        return os.path.basename(self._get_dataproduct(obj).data.name)

    def get_format(self, obj):
        filename = self.get_name(obj)
        return filename.split('.')[-1]

    def get_url(self, obj):
        return self._get_dataproduct(obj).data.url

    def get_created(self, obj):
        return TimestampField().to_representation(obj.terminal_timestamp)

    def get_frames(self, obj):
        return obj.input_files.count()


class TargetDetailSerializer(serializers.Serializer):
    """
    Response for target detail API: includes information about the target and
    its timelapses
    """
    target = TargetSerializer()
    timelapses = serializers.ListSerializer(child=TimelapsePipelineSerializer())
    data = PhotometrySerializer()


class ObservationAlertSerializer(serializers.Serializer):
    target = serializers.IntegerField(min_value=1)
    template_name = serializers.CharField()
    facility = serializers.CharField()
    overrides = serializers.DictField(required=False)
    email = serializers.EmailField()
