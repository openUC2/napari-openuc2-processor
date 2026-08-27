"""Tests for widgets._load.open_path (no Qt event loop / real viewer needed)."""

import os

from openuc2_processor.widgets._load import open_path


class FakeViewer:
    """Records what open() was called with; no real napari/Qt involved."""

    def __init__(self):
        self.calls = []

    def open(self, paths, stack=False, **kwargs):
        self.calls.append({"paths": paths, "stack": stack})
        return list(paths) if isinstance(paths, (list, tuple)) else [paths]


def _make_timelapse_dataset(base_dir, n_timepoints=20):
    """Reproduce the reported layout: one unpadded ``experimentN`` dir per
    timepoint (0..19, so lexicographic order != numeric order), each holding
    a single .tif tile, plus a stray top-level report .png."""
    for tp in range(n_timepoints):
        tile_dir = os.path.join(
            str(base_dir),
            f"20260827_120758_experiment0_{tp}_experiment_0_Position-1",
            "tiles",
            f"timepoint_{tp:04d}",
        )
        os.makedirs(tile_dir, exist_ok=True)
        ts = f"12{tp:04d}"  # monotonically increasing stand-in timestamp
        fname = f"t20260827_{ts}_x24000000_y114040000_z2450000_c0_635_i0003_p1023.tif"
        with open(os.path.join(tile_dir, fname), "wb") as f:
            f.write(b"\x00")

    # incidental non-tif report artifact sitting alongside the timepoint dirs
    with open(os.path.join(str(base_dir), "step_timings_violin.png"), "wb") as f:
        f.write(b"\x00")


def test_open_path_stack_excludes_other_extensions(tmp_path):
    _make_timelapse_dataset(tmp_path)
    viewer = FakeViewer()

    layers = open_path(viewer, str(tmp_path), as_stack=True)

    assert len(viewer.calls) == 1
    call = viewer.calls[0]
    assert call["stack"] is True
    assert len(call["paths"]) == 20
    assert all(p.endswith(".tif") for p in call["paths"])
    assert layers


def test_open_path_stack_uses_natural_sort_order(tmp_path):
    _make_timelapse_dataset(tmp_path)
    viewer = FakeViewer()

    open_path(viewer, str(tmp_path), as_stack=True)

    paths = viewer.calls[0]["paths"]
    # dir names are unpadded ("_2_", "_10_"); a plain string sort would put
    # "_10_".."_19_" before "_2_"..."_9_" — assert numeric/chronological order.
    timepoints = [
        int(os.path.basename(os.path.dirname(p)).split("timepoint_")[1])
        for p in paths
    ]
    assert timepoints == sorted(timepoints)
    assert timepoints == list(range(20))
