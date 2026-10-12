# Media helper provenance

Extracted from inherited `app/worker/operations.py`, `hls.py`, `probe.py` and
`validation.py`, imported source commit `885453726d629c524bf511d665311863d9bc70a5`.
The fixed clip/crop/scale/convert pipeline, HLS rung selection, codecs and source
geometry checks are retained. Command inputs now use plain dictionaries. Process
execution, deadline/cancellation, HTTP and storage belong to Processing. Probe
parsing is isolated from execution; the worker supervises ffprobe like FFmpeg.
