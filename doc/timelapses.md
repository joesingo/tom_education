# Timelapses

On the detailed view for a target under 'Manage Data', a timelapse of FITS data
products can be created as animated GIFs or MP4 or WebM video.

Options can be configured with `TOM_EDUCATION_TIMELAPSE_SETTINGS` in
`settings.py`, e.g.

```python
TOM_EDUCATION_TIMELAPSE_SETTINGS = {
    'format': 'webm',
    'fps': 15,
    'size': 500
}
```

Here 'size' is the maximum width/height to use. The aspect ratio of the input
files is maintained.

## Management Command

Timelapses can also be created through the management command `create_timelapses`.

```
./manage.py create_timelapse <target PK>
```

This will create a timelapse for all reduced data products associated with the
given target that are contained in the data product group 'Good quality data'.
This group name can be changed by setting `TOM_EDUCATION_TIMELAPSE_GROUP_NAME`
in `settings.py`.
