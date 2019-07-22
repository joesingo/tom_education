from django.shortcuts import reverse
from rest_framework import serializers

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
            'identifier', 'created', 'status', 'terminal_timestamp', 'failure_message', 'view_url'
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
            'identifier', 'created', 'status', 'terminal_timestamp', 'failure_message', 'logs',
            'group_name', 'group_url'
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
