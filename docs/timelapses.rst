Timelapses
==========

On the 'Data View' page for a target, a timelapse of FITS data products can be
created as animated GIFs or MP4 or WebM video by selecting 'Timelapse' in the
'Pipeline process' dropdown.

After selecting 'Timelapse', two checkboxes are shown to optionally perform
extra processing of each frame when the timelapse is created:

* 'Process each frame to achieve a consistent background brightness across the timelapse'
* 'Crop each frame in the timelapse around its centre pixel'

The first option prevents the 'flickering' that can occur when there are
differences in the background brightness across the input files. Note that it
can significantly increase the processing time.

The second setting can be used to 'zoom in' on the target in the centre of each
frame of the timelapse.

Other options can be configured with ``TOM_EDUCATION_TIMELAPSE_SETTINGS`` in
``settings.py``, e.g. ::

    TOM_EDUCATION_TIMELAPSE_SETTINGS = {
        'format': 'webm',  # Choose from 'gif', 'mp4' or 'webm'
        'fps': 15,
        'size': 500
        # Scale factor to use when creating timelapses with the 'crop' flag; the
        # dimensions of the original frames are scaled by `scale` in the timelapse
        'crop_scale': 0.5,
    }

Here 'size' is the maximum width/height to use. The aspect ratio of the input
files is maintained.

Management Command
------------------

Timelapses can also be created through the management command
``create_timelapses``. ::

    ./manage.py create_timelapse <target PK>

This will create a timelapse for all reduced data products associated with the
given target that are contained in the data product group 'Good quality data'.
This group name can be changed by setting ``TOM_EDUCATION_TIMELAPSE_GROUP_NAME``
in ``settings.py``.
