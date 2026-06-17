"""Processor registry — the extension seam for processing modes.

Adding a new processing method is a single ``PROCESSORS`` entry: both the engine
call and the GUI checkbox (which is generated from this dict) appear
automatically.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from . import engine
from .engine import ExperimentGrid


@dataclass
class ProcessParams:
    """User-tunable parameters shared across processors."""
    output_dir: Optional[str] = None      # default: <input>/converted
    protocol_json: Optional[str] = None   # auto-detected when None
    pixel_size: float = 1.0               # microns/pixel (ashlar)
    maximum_shift: float = 50.0           # microns (ashlar)
    align_channel: int = 0                # ashlar alignment channel


@dataclass
class Processor:
    """A single registered processing mode."""
    key: str                              # stable id, e.g. "composite"
    label: str                            # human label for the GUI checkbox
    description: str                      # tooltip
    subdir: str                           # output sub-folder name
    run: Callable[[ExperimentGrid, str, ProcessParams], List[str]]
    needs_ashlar_params: bool = False     # show pixel-size/shift/align controls


# -- per-mode run wrappers --------------------------------------------------
# Each takes (grid, out_subdir, params) and returns the list of written paths.

def _run_composite(grid, out, params):
    return engine.build_composite_stacks(grid, out)


def _run_stitch(grid, out, params):
    return engine.build_stitched_tiffs(grid, out)


def _run_mip(grid, out, params):
    return engine.build_mip_stitched(grid, out)


def _run_mip_composite(grid, out, params):
    return engine.build_mip_composite(grid, out)


def _run_focus(grid, out, params):
    return engine.build_best_focus_stitched(grid, out)


def _run_tile_config(grid, out, params):
    return engine.write_tile_configuration(grid, out)


def _run_timelapse(grid, out, params):
    return engine.build_timelapse(grid, out, use_mip=False)


def _run_timelapse_mip(grid, out, params):
    return engine.build_timelapse(grid, out, use_mip=True)


def _run_ashlar(grid, out, params):
    return engine.build_ashlar_stitched(
        grid, out,
        pixel_size=params.pixel_size,
        maximum_shift=params.maximum_shift,
        align_channel=params.align_channel,
    )


PROCESSORS: Dict[str, Processor] = {
    "composite": Processor(
        "composite", "Composite stack (napari)",
        "Per-position TCZYX hyperstack — best for napari.",
        "composite", _run_composite),
    "stitch": Processor(
        "stitch", "Stitched (grid, Fiji)",
        "Per-channel/timepoint grid stitch (MIP over Z per position).",
        "stitched", _run_stitch),
    "mip": Processor(
        "mip", "MIP stitched",
        "Per-position max-intensity projection over Z, then stitched.",
        "mip_stitched", _run_mip),
    "mip-composite": Processor(
        "mip-composite", "MIP composite (napari)",
        "Per-channel MIP-stitched canvases merged into a napari composite.",
        "mip_composite", _run_mip_composite),
    "focus": Processor(
        "focus", "Best-focus stitched",
        "Select the sharpest Z-plane per position (post-proc autofocus), then stitch.",
        "best_focus", _run_focus),
    "tile-config": Processor(
        "tile-config", "Fiji TileConfiguration.txt",
        "Write Fiji Grid/Collection stitching configuration files.",
        "tile_config", _run_tile_config),
    "timelapse": Processor(
        "timelapse", "Timelapse (best-focus)",
        "Concatenate timepoints into a TCYX hyperstack (best-focus plane).",
        "timelapse", _run_timelapse),
    "timelapse-mip": Processor(
        "timelapse-mip", "Timelapse (MIP)",
        "Concatenate timepoints into a TCYX hyperstack (MIP over Z).",
        "timelapse_mip", _run_timelapse_mip),
    "ashlar": Processor(
        "ashlar", "Ashlar stitch (sub-pixel)",
        "Sub-pixel registered stitching via ashlarUC2 (requires overlap).",
        "ashlar", _run_ashlar, needs_ashlar_params=True),
}

# Order presented in the GUI.
PROCESSOR_ORDER: List[str] = list(PROCESSORS.keys())


def run_processors(
    input_dir: str,
    keys: List[str],
    params: Optional[ProcessParams] = None,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> Dict[str, List[str]]:
    """Discover tiles under *input_dir* and run the selected processors.

    Parameters
    ----------
    input_dir : str
        A tiles directory, a session base directory, or a parent containing
        ``tiles/`` — auto-detected.
    keys : list[str]
        Keys from :data:`PROCESSORS` to run, in any order.
    params : ProcessParams
        Shared parameters; ``output_dir`` defaults to ``<input_dir>/converted``.
    progress_cb : callable(label, done, total)
        Optional callback invoked before each processor runs.

    Returns
    -------
    dict[str, list[str]]
        Mapping of processor key -> list of written output file paths.
    """
    params = params or ProcessParams()
    input_dir = os.path.abspath(input_dir)
    out_base = params.output_dir or os.path.join(input_dir, "converted")
    os.makedirs(out_base, exist_ok=True)

    selected = [k for k in PROCESSOR_ORDER if k in set(keys)]
    if not selected:
        raise ValueError("No processing modes selected.")

    tiles = engine.discover_any(input_dir, protocol_json=params.protocol_json)
    if not tiles:
        raise RuntimeError(
            f"No ImSwitch tiles found under {input_dir}. Expected files named "
            "t<date>_x..._y..._z..._c..._<channel>_i..._p....tif"
        )
    grid = ExperimentGrid.from_tiles(tiles)

    results: Dict[str, List[str]] = {}
    total = len(selected)
    for i, key in enumerate(selected):
        proc = PROCESSORS[key]
        if progress_cb is not None:
            progress_cb(proc.label, i, total)
        out_sub = os.path.join(out_base, proc.subdir)
        try:
            results[key] = proc.run(grid, out_sub, params)
        except Exception as exc:  # one mode failing shouldn't abort the rest
            print(f"  ERROR in processor '{key}': {exc}")
            results[key] = []
    if progress_cb is not None:
        progress_cb("done", total, total)
    return results
