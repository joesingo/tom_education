from io import StringIO
import logging
from pathlib import Path

import autovar
import numpy as np

from tom_education.models.async_process import AsyncError
from tom_education.models.pipelines import PipelineProcess


class AutovarLogBuffer(StringIO):
    """
    Thin wrapper around StringIO that logs messages against a `AutovarProcess`
    on write
    """
    def __init__(self, process, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.process = process

    def write(self, s):
        self.process.log(s, end='')
        return super().write(s)


class AutovarProcess(PipelineProcess):
    # Directories to find output files in after autovar has been run
    output_dirs = ('outputcats', 'outputplots')

    class Meta:
        proxy = True

    def copy_input_files(self, tmpdir):
        """
        Copy the input files to the given temporary directory
        """
        for prod in self.input_files.all():
            dest = tmpdir / Path(prod.data.path).name  # Use basename of original file
            dest.write_bytes(prod.data.read())

    def do_pipeline(self, tmpdir):
        """
        Call autovar to perform the actual analysis
        """
        self.copy_input_files(tmpdir)

        buf = AutovarLogBuffer(self)
        logger = logging.getLogger('autovar')
        logger.setLevel(logging.INFO)
        logger.addHandler(logging.StreamHandler(buf))

        targets = np.array([self.target.ra, self.target.dec, 0, 0])
        filetype = 'psx'  # TODO: determine this from the input files

        try:
            with self.update_status('Setting up folders'):
                paths = autovar.folder_setup(tmpdir)
            with self.update_status('Gathering files'):
                filelist, filtercode = autovar.gather_files(paths, filetype=filetype)
            with self.update_status('Finding stars'):
                autovar.find_stars(targets, paths, filelist)
            with self.update_status('Finding comparisons'):
                autovar.find_comparisons(tmpdir)
            with self.update_status('Calculating curves'):
                autovar.calculate_curves(targets, parentPath=tmpdir)
            with self.update_status('Performing photometric calculations'):
                autovar.photometric_calculations(targets, paths=paths)
            with self.update_status('Making plots'):
                autovar.make_plots(filterCode=filtercode, paths=paths)
        except autovar.AutovarException as ex:
            raise AsyncError(str(ex))

        yield from self.gather_outputs(tmpdir)

    def gather_outputs(self, tmpdir):
        """
        Yield Path objects for autovar output files
        """
        for outdir_name in self.output_dirs:
            outdir = tmpdir / Path(outdir_name)
            if not outdir.is_dir():
                continue
            for path in outdir.iterdir():
                if not path.is_file():
                    continue
                yield path
