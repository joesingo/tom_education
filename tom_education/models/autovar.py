from contextlib import contextmanager
from io import StringIO
import logging
import tempfile
from pathlib import Path

import autovar
from django.core.files.base import ContentFile
from django.db import models
import numpy as np
from tom_dataproducts.models import DataProduct, DataProductGroup

from tom_education.models.async_process import AsyncError, AsyncProcess, ASYNC_STATUS_CREATED


class AutovarLogBuffer(StringIO):
    """
    Thin wrapper around StringIO that appends to the `logs` field of a
    `AutovarProcess` on write
    """
    def __init__(self, process, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.process = process

    def write(self, s):
        if not self.process.logs:
            self.process.logs = ''
        self.process.logs += s
        self.process.save()
        return super().write(s)


class AutovarProcess(AsyncProcess):
    # Directories to find output files in after autovar has been run
    output_dirs = ('outputcats', 'outputplots')

    input_files = models.ManyToManyField(DataProduct, related_name='autovar')
    logs = models.TextField(null=True, blank=True)

    def run(self):
        if self.target is None:
            raise AsyncError('Process must have an associated target')
        if not self.input_files.exists():
            raise AsyncError('No input files to analyse')

        buf = AutovarLogBuffer(self)
        logger = logging.getLogger('autovar')
        logger.setLevel(logging.INFO)
        logger.addHandler(logging.StreamHandler(buf))

        with self.autovar_dir() as autovar_dir:
            try:
                self.do_autovar(autovar_dir)
            except autovar.AutovarException as ex:
                raise AsyncError(str(ex))

            # Get outputs
            group = DataProductGroup.objects.create(name=f'{self.identifier}_outputs')
            for path in self.gather_outputs(autovar_dir):
                product_id = f'{self.identifier}_{path.name}'
                prod = DataProduct.objects.create(product_id=product_id, target=self.target)
                prod.group.add(group)
                prod.data.save(product_id, ContentFile(path.read_bytes()))

        self.status = ASYNC_STATUS_CREATED
        self.save()

    @contextmanager
    def autovar_dir(self):
        """
        Context manager to create a temporary directory, copy over the input
        files to the new directory, and yield a Path object
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            for i, prod in enumerate(self.input_files.all()):
                dest = path / Path(prod.data.path).name
                dest.write_bytes(prod.data.read())
            try:
                yield path
            finally:
                pass

    def do_autovar(self, autovar_dir):
        """
        Call autovar to perform the actual analysis
        """
        targets = np.array([self.target.ra, self.target.dec, 0, 0])
        paths = autovar.folder_setup(autovar_dir)
        filetype = 'fz'  # TODO: determine this from the input files
        filelist, filtercode = autovar.gather_files(paths, filetype=filetype)

        with self.update_status('Finding stars'):
            autovar.find_stars(targets, paths, filelist)
        with self.update_status('Finding comparisons'):
            autovar.find_comparisons(autovar_dir)
        with self.update_status('Calculating curves'):
            autovar.calculate_curves(targets, parentPath=autovar_dir)
        with self.update_status('Performing photometric calculations'):
            autovar.photometric_calculations(targets, paths=paths)
        with self.update_status('Making plots'):
            autovar.make_plots(filterCode=filtercode, paths=paths)

    def gather_outputs(self, autovar_dir):
        """
        Yield Path objects for files in the output directories in the given
        autovar directory
        """
        for outdir_name in self.output_dirs:
            outdir = autovar_dir / Path(outdir_name)
            if not outdir.is_dir():
                continue
            for path in outdir.iterdir():
                if not path.is_file():
                    continue
                yield path

    @contextmanager
    def update_status(self, status):
        yield None
        self.status = status
        self.save()
