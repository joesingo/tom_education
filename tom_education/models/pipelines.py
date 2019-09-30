from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime
import json
import tempfile
from pathlib import Path
import re
import os.path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.utils.module_loading import import_string
from tom_dataproducts.models import DataProduct, ReducedDatum, DataProductGroup

from tom_education.models.async_process import AsyncError, AsyncProcess, ASYNC_STATUS_CREATED
from tom_education.utils import assert_valid_suffix


class InvalidPipelineError(Exception):
    """
    Failed to import a PipelineProcess subclass from settings
    """


PipelineOutput = namedtuple('PipelineOutput', ['path', 'output_type', 'tag'],
                            defaults=('',))  # tag is optional


class PipelineProcess(AsyncProcess):
    short_name = 'pipeline'
    flags = None
    allowed_suffixes = None

    input_files = models.ManyToManyField(DataProduct, related_name='pipeline')
    group = models.ForeignKey(DataProductGroup, null=True, blank=True, on_delete=models.SET_NULL)
    logs = models.TextField(null=True, blank=True)
    flags_json = models.TextField(null=True, blank=True)

    def run(self):
        if self.target is None:
            raise AsyncError('Process must have an associated target')
        if not self.input_files.exists():
            raise AsyncError('No input files to process')
        # Check file suffixes
        if self.allowed_suffixes:
            for prod in self.input_files.all():
                filename = prod.data.name or ''
                try:
                    assert_valid_suffix(os.path.basename(filename), self.allowed_suffixes)
                except AssertionError as ex:
                    raise AsyncError("Error running pipeline {}".format(ex))

        with tempfile.TemporaryDirectory() as tmpdir_name:
            tmpdir = Path(tmpdir_name)

            # Do the actual work
            flags = json.loads(self.flags_json) if self.flags_json else {}
            outputs = self.do_pipeline(tmpdir, **flags)

            # Save outputs
            new_dps = []
            for output in outputs:
                if not isinstance(output, PipelineOutput):
                    output = PipelineOutput(*output)

                path, output_type, tag = output
                identifier = f'{self.identifier}_{path.name}'

                if output_type == DataProduct:
                    prod = DataProduct.objects.create(product_id=identifier, target=self.target, tag=tag)
                    prod.data.save(identifier, ContentFile(path.read_bytes()))
                    new_dps.append(prod)

                elif output_type == ReducedDatum:
                    ReducedDatum.objects.create(
                        target=self.target,
                        data_type=tag,
                        source_name=identifier,
                        timestamp=datetime.now(),
                        value=path.read_text()
                    )

                else:
                    raise AsyncError(f"Invalid output type '{output_type}'")

            # Create a group to collect DataProduct outputs into
            if new_dps:
                self.group = DataProductGroup.objects.create(name=f'{self.identifier}_outputs')
                for prod in new_dps:
                    prod.group.add(self.group)
                    prod.save()

        self.status = ASYNC_STATUS_CREATED
        self.save()

    def do_pipeline(self, tmpdir):
        """
        Perform the actual work, and return a sequence of PipelineOutput
        objects (or tuples) for each output file to be saved.

        Should raise AsyncError(failure_message) on failure
        """
        raise NotImplementedError('Must be implemented in child classes')

    @contextmanager
    def update_status(self, status):
        self.status = status
        self.save()
        yield None

    def log(self, msg, end='\n'):
        if not self.logs:
            self.logs = ''
        self.logs += msg + end
        self.save()

    @classmethod
    def get_available(cls):
        """
        Return the pipelines dict from settings.py
        """
        return getattr(settings, 'TOM_EDUCATION_PIPELINES', {})

    @classmethod
    def get_subclass(cls, name):
        """
        Return the sub-class corresponding to the name given
        """
        try:
            pipeline_cls = import_string(cls.get_available()[name])
        except ImportError as ex:
            raise InvalidPipelineError(ex)

        # Check imported object is a class, and has PipelineProcess as a parent
        err = '{} does not look like a PipelineProcess sub-class'.format(pipeline_cls)
        try:
            if not issubclass(pipeline_cls, PipelineProcess):
                raise InvalidPipelineError(err)
        except TypeError:  # TypeError raised by issubclass() if first arg is not a class
            raise InvalidPipelineError(err)

        try:
            cls.validate_flags(pipeline_cls.flags)
        except AssertionError:
            raise InvalidPipelineError("Invalid 'flags' attribute in {}".format(pipeline_cls))
        return pipeline_cls

    @classmethod
    def validate_flags(cls, flags):
        """
        Validate a class's `flags` attribute. Raises AssertionError if
        invalid
        """
        if flags is None:
            return
        assert isinstance(flags, dict)
        # `name` will be used as an ID in the HTML, so must not contain
        # whitespace
        for name, info in flags.items():
            assert re.match(r'[^\s]+$', name)
            assert isinstance(info, dict)
            assert 'default' in info
            assert 'long_name' in info

    @classmethod
    def create_timestamped(cls, target, products, flags=None):
        date_str = datetime.now().strftime('%Y%m%d%H%M%S')
        identifier = f'{cls.short_name}_{target.pk}_{date_str}'
        kwargs = {
            'identifier': identifier,
            'target': target
        }
        if flags:
            kwargs['flags_json'] = json.dumps(flags)

        pipe = cls.objects.create(**kwargs)
        pipe.input_files.add(*products)
        pipe.save()
        return pipe
