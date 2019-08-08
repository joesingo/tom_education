import os.path

from django.shortcuts import reverse
from rest_framework import serializers
from tom_targets.models import Target

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
        fields = ['identifier', 'name', 'name2', 'name3', 'extra_fields']


class TimelapseSerializer(serializers.Serializer):
    """
    Serialize basic info for a timelapse, including the (relative) URL to the
    actual timelapse file
    """
    name = serializers.SerializerMethodField()
    format = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    created = serializers.SerializerMethodField()
    frames = serializers.SerializerMethodField()

    def get_name(self, obj):
        return os.path.basename(obj.data.name)

    def get_format(self, obj):
        return obj.fmt

    def get_url(self, obj):
        return obj.data.url

    def get_created(self, obj):
        return TimestampField().to_representation(obj.created)

    def get_frames(self, obj):
        return obj.frames.count()


class TargetDetailSerializer(serializers.Serializer):
    """
    Response for target detail API: includes information about the target and
    its timelapses
    """
    target = TargetSerializer()
    timelapses = serializers.ListSerializer(child=TimelapseSerializer())


class ObservationAlertSerializer(serializers.Serializer):
    target = serializers.IntegerField(min_value=1)
    template_name = serializers.CharField()
    facility = serializers.CharField()
    overrides = serializers.DictField(required=False)
    email = serializers.EmailField()
