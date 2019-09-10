# Timelapses

On the detailed view for a target under 'Manage Data', a timelapse of FITS data
products can be created as animated GIFs or MP4 or WebM video.

Options can be configured with `TOM_EDUCATION_TIMELAPSE_SETTINGS` in
`settings.py`, e.g.

```python
TOM_EDUCATION_TIMELAPSE_SETTINGS = {
    'format': 'webm',  # Choose from 'gif', 'mp4' or 'webm'
    'fps': 15,
    'size': 500
    # If True, process each frame to achieve a consistent background brightness
    # across the timelapse
    'normalise_background': False,
    # Optionally crop each frame in the timelapse around its centre pixel. The
    # dimensions of the frame are scaled by `scale`
    'crop': {
        'scale': 0.5,
        'enabled': False
    },
}
```

Here 'size' is the maximum width/height to use. The aspect ratio of the input
files is maintained.

The `normalise_background` setting prevent the 'flickering' that can occur when
there are differences in the background brightness across the input files, but
significantly increases processing time. Is is disabled by default.

The `crop` setting can be used to 'zoom in' on the target in the centre of each
frame of the timelapse.

## Management Command

Timelapses can also be created through the management command `create_timelapses`.

```
./manage.py create_timelapse <target PK>
```

This will create a timelapse for all reduced data products associated with the
given target that are contained in the data product group 'Good quality data'.
This group name can be changed by setting `TOM_EDUCATION_TIMELAPSE_GROUP_NAME`
in `settings.py`.
