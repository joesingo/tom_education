from contextlib import contextmanager
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import models
from tom_dataproducts.models import DataProduct, DataProductGroup

from tom_education.models.async_process import AsyncError, AsyncProcess, ASYNC_STATUS_CREATED


class PipelineProcess(AsyncProcess):
    input_files = models.ManyToManyField(DataProduct, related_name='pipeline')
    group = models.ForeignKey(DataProductGroup, null=True, blank=True, on_delete=models.SET_NULL)
    logs = models.TextField(null=True, blank=True)

    def run(self):
        if self.target is None:
            raise AsyncError('Process must have an associated target')
        if not self.input_files.exists():
            raise AsyncError('No input files to analyse')

        with tempfile.TemporaryDirectory() as tmpdir_name:
            tmpdir = Path(tmpdir_name)

            # Do the actual work
            output_paths = self.do_pipeline(tmpdir)

            # Save outputs
            self.group = DataProductGroup.objects.create(name=f'{self.identifier}_outputs')
            for path in output_paths:
                product_id = f'{self.identifier}_{path.name}'
                prod = DataProduct.objects.create(product_id=product_id, target=self.target)
                prod.group.add(self.group)
                prod.data.save(product_id, ContentFile(path.read_bytes()))

        self.status = ASYNC_STATUS_CREATED
        self.save()

    def do_pipeline(self, tmpdir):
        """
        Perform the actual work, and return a sequence of pathlib.Path objects
        for each output file to be saved.

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
