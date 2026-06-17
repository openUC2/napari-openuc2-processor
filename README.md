# napari-openuc2-processor

A self-contained [napari](https://napari.org) plugin to **download** and
**process** openUC2 / ImSwitch microscopy datasets.

```bash
pip install -e .
# open the downloader pre-filled with a source:
napari --plugin openuc2-processor 13457227.zarr
napari --plugin openuc2-processor "http://HOST:PORT/imswitch/api/FileManager/download/recordings/exp.ome.zarr"
napari --plugin openuc2-processor /path/to/local/tiles
```

## Features

- **Dataset Downloader** widget
  - Source can be a **local path**, a **full http(s) URL**, or a **bare numeric
    ID** (resolved against a configurable base — Zenodo by default).
  - Configurable storage directory (default `~/Downloads`, "Change…" button).
  - Progress bar with **Start / Stop / Restart**.
  - Optional "load into napari as a stack/layer when done".
- **Dataset Processor** widget — a GUI over the ImSwitch tile-conversion engine
  (composite, stitch, mip, mip-composite, focus, tile-config, timelapse,
  timelapse-mip, ashlar). Pick an input folder, select modes, run, and
  optionally visualize the results in napari (otherwise they are just saved).

## Extending

- **New processing mode:** add one `Processor` entry to
  `openuc2_processor/processing/registry.py`. The engine call and the widget
  checkbox appear automatically.
- **New download source:** add a `Source` subclass under
  `openuc2_processor/sources/` and register it in `resolve_source`.

The processing engine is vendored from
`scripts/convert_experiment_tiffs.py` in the ImSwitch repo and kept in sync
manually; the standalone CLI script remains usable on its own.
