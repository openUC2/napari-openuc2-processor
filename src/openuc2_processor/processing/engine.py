#!/usr/bin/env python3
"""Tile-conversion engine for ImSwitch experiment TIFFs.

Vendored and lightly refactored from ``scripts/convert_experiment_tiffs.py`` in
the ImSwitch repository.  The refactor: every ``build_*`` / ``write_*`` function
now **returns the list of output paths it wrote**, so the GUI can optionally load
them into napari.  The logic is otherwise unchanged.

Filename convention produced by ImSwitch OMEWriter._write_individual_tiff:
    t{YYYYMMDD_HHMMSS}_x{X}_y{Y}_z{Z}_c{cIdx}_{channelName}_i{iter}_p{power}.tif
    X, Y, Z are microns * 1000 (integer, sub-micron precision).
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import tifffile as tif
except ImportError:  # pragma: no cover
    raise ImportError("tifffile is required: pip install tifffile")


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

_FILENAME_RE = re.compile(
    r"t(?P<timestamp>\d{8}_\d{6})"
    r"_x(?P<x>-?\d+)"
    r"_y(?P<y>-?\d+)"
    r"_z(?P<z>-?\d+)"
    r"_c(?P<c_idx>\d+)"
    r"_(?P<channel>[A-Za-z0-9_]+?)"
    r"_i(?P<iter>\d+)"
    r"_p(?P<power>\d+)"
    r"\.tif$"
)


@dataclass
class TileInfo:
    """Parsed metadata for a single TIFF tile."""
    filepath: str
    timestamp: str
    x: int          # microns * 1000
    y: int
    z: int
    c_idx: int
    channel: str
    iterator: int
    power: int
    timepoint: int = 0
    ix: int = -1
    iy: int = -1


def parse_filename(filepath: str) -> Optional[TileInfo]:
    """Parse an individual TIFF filename into a TileInfo."""
    basename = os.path.basename(filepath)
    m = _FILENAME_RE.match(basename)
    if m is None:
        return None
    return TileInfo(
        filepath=filepath,
        timestamp=m.group("timestamp"),
        x=int(m.group("x")),
        y=int(m.group("y")),
        z=int(m.group("z")),
        c_idx=int(m.group("c_idx")),
        channel=m.group("channel"),
        iterator=int(m.group("iter")),
        power=int(m.group("power")),
    )


# ---------------------------------------------------------------------------
# JSON protocol loader
# ---------------------------------------------------------------------------

def _find_protocol_json(tiles_dir: str) -> Optional[str]:
    """Auto-locate the experiment protocol JSON next to the tiles directory."""
    search_dirs = [
        os.path.dirname(tiles_dir),
        os.path.dirname(os.path.dirname(tiles_dir)),
    ]
    for d in search_dirs:
        if not d or not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if fname.endswith("_protocol.json"):
                return os.path.join(d, fname)
    return None


def load_protocol_grid(json_path: str) -> Dict[int, Tuple[int, int]]:
    """Map iterator -> (iX, iY) from the snake_tiles list in the protocol JSON."""
    with open(json_path) as f:
        data = json.load(f)

    iterator_to_grid: Dict[int, Tuple[int, int]] = {}
    for row in data.get("snake_tiles", []):
        for entry in row:
            it = entry.get("iterator")
            ix = entry.get("iX")
            iy = entry.get("iY")
            if it is not None and ix is not None and iy is not None:
                iterator_to_grid[it] = (int(ix), int(iy))
    return iterator_to_grid


def _cluster_to_indices(values: List[int]) -> Dict[int, int]:
    """Map raw coordinate values to 0-based indices by sorting unique values."""
    unique = sorted(set(values))
    return {v: i for i, v in enumerate(unique)}


def assign_grid_indices(tiles: List[TileInfo], protocol_json: Optional[str]) -> None:
    """Assign ix/iy grid indices to every TileInfo in-place."""
    if protocol_json and os.path.isfile(protocol_json):
        print(f"  Using protocol JSON: {os.path.basename(protocol_json)}")
        iter_map = load_protocol_grid(protocol_json)

        xy_groups: Dict[Tuple[int, int], List[TileInfo]] = {}
        for tile in tiles:
            key = (tile.x, tile.y)
            xy_groups.setdefault(key, []).append(tile)

        ranked_xy = sorted(xy_groups.keys(),
                           key=lambda k: min(t.iterator for t in xy_groups[k]))
        ranked_json = sorted(iter_map.keys())

        if len(ranked_xy) != len(ranked_json):
            print(f"  WARNING: {len(ranked_xy)} unique XY positions but "
                  f"{len(ranked_json)} JSON entries - using coordinate fallback")
            x_map = _cluster_to_indices([t.x for t in tiles])
            y_map = _cluster_to_indices([t.y for t in tiles])
            for tile in tiles:
                tile.ix = x_map[tile.x]
                tile.iy = y_map[tile.y]
            return

        xy_to_grid: Dict[Tuple[int, int], Tuple[int, int]] = {}
        for xy_key, json_iter in zip(ranked_xy, ranked_json):
            xy_to_grid[xy_key] = iter_map[json_iter]

        for tile in tiles:
            ix, iy = xy_to_grid[(tile.x, tile.y)]
            tile.ix = ix
            tile.iy = iy

        min_ix = min(t.ix for t in tiles)
        min_iy = min(t.iy for t in tiles)
        for tile in tiles:
            tile.ix -= min_ix
            tile.iy -= min_iy

        print(f"  Grid indices assigned from JSON for {len(tiles)}/{len(tiles)} tiles "
              f"({len(ranked_xy)} unique XY positions)")
    else:
        print("  No protocol JSON found - deriving grid indices from stage coordinates")
        x_map = _cluster_to_indices([t.x for t in tiles])
        y_map = _cluster_to_indices([t.y for t in tiles])
        for tile in tiles:
            tile.ix = x_map[tile.x]
            tile.iy = y_map[tile.y]


# ---------------------------------------------------------------------------
# Tile discovery
# ---------------------------------------------------------------------------

def discover_tiles(tiles_dir: str, protocol_json: Optional[str] = None) -> List[TileInfo]:
    """Walk the tiles directory, parse all TIFF filenames, assign grid indices."""
    tiles: List[TileInfo] = []
    tiles_path = Path(tiles_dir)

    for tp_dir in sorted(tiles_path.iterdir()):
        if not tp_dir.is_dir():
            continue
        tp_match = re.match(r"timepoint_(\d+)", tp_dir.name)
        tp_idx = int(tp_match.group(1)) if tp_match else 0

        for tif_file in sorted(tp_dir.glob("*.tif")):
            info = parse_filename(str(tif_file))
            if info is not None:
                info.timepoint = tp_idx
                tiles.append(info)

    if not tiles:
        print(f"No matching TIFF files found under {tiles_dir}")
        return tiles

    print(f"Discovered {len(tiles)} tiles across "
          f"{len(set(t.timepoint for t in tiles))} timepoint(s)")

    if protocol_json is None:
        protocol_json = _find_protocol_json(tiles_dir)

    assign_grid_indices(tiles, protocol_json)
    return tiles


_EXPERIMENT_DIR_RE = re.compile(r"_experiment\d+_(\d+)_")


def _is_multi_experiment_dir(base_dir: str) -> bool:
    """Return True if base_dir contains experiment-series subdirectories."""
    for entry in os.scandir(base_dir):
        if entry.is_dir() and _EXPERIMENT_DIR_RE.search(entry.name):
            return True
    return False


def discover_tiles_from_base_dir(
    base_dir: str,
    protocol_json: Optional[str] = None,
) -> List[TileInfo]:
    """Discover tiles from a session base dir with one experiment subdir per timepoint."""
    tiles: List[TileInfo] = []
    base_path = Path(base_dir)

    experiment_dirs: List[Tuple[int, Path]] = []
    for subdir in sorted(base_path.iterdir()):
        if not subdir.is_dir():
            continue
        m = _EXPERIMENT_DIR_RE.search(subdir.name)
        if m is None:
            continue
        experiment_dirs.append((int(m.group(1)), subdir))

    if not experiment_dirs:
        return discover_tiles(base_dir, protocol_json)

    for series_idx, exp_dir in sorted(experiment_dirs):
        tiles_subdir = exp_dir / "tiles"
        if not tiles_subdir.is_dir():
            continue
        for tp_dir in sorted(tiles_subdir.iterdir()):
            if not tp_dir.is_dir():
                continue
            for tif_file in sorted(tp_dir.glob("*.tif")):
                info = parse_filename(str(tif_file))
                if info is not None:
                    info.timepoint = series_idx
                    tiles.append(info)

    if not tiles:
        print(f"No matching TIFF files found under {base_dir}")
        return tiles

    print(
        f"Discovered {len(tiles)} tiles across "
        f"{len(set(t.timepoint for t in tiles))} timepoints "
        f"from {len(experiment_dirs)} experiment directories"
    )
    assign_grid_indices(tiles, None)
    return tiles


def discover_any(input_dir: str, protocol_json: Optional[str] = None) -> List[TileInfo]:
    """Auto-detect multi-experiment vs plain tiles layout and discover tiles.

    Also tolerates being handed a session/experiment directory that *contains* a
    ``tiles/`` subfolder by descending into it.
    """
    input_dir = os.path.abspath(input_dir)
    if _is_multi_experiment_dir(input_dir):
        print(f"Detected multi-experiment timelapse layout under: {input_dir}")
        return discover_tiles_from_base_dir(input_dir, protocol_json=protocol_json)

    # Plain tiles dir? (contains timepoint_XXXX subfolders)
    has_timepoints = any(
        re.match(r"timepoint_(\d+)", p.name)
        for p in Path(input_dir).iterdir() if p.is_dir()
    )
    if not has_timepoints:
        nested = os.path.join(input_dir, "tiles")
        if os.path.isdir(nested):
            print(f"Descending into tiles/ under: {input_dir}")
            return discover_any(nested, protocol_json)
    return discover_tiles(input_dir, protocol_json=protocol_json)


# ---------------------------------------------------------------------------
# Grouping helpers
# ---------------------------------------------------------------------------

def _unique_sorted(values):
    return sorted(set(values))


@dataclass
class ExperimentGrid:
    """Describes the full dimensionality of the experiment."""
    timepoints: List[int] = field(default_factory=list)
    ix_positions: List[int] = field(default_factory=list)
    iy_positions: List[int] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)
    c_indices: List[int] = field(default_factory=list)
    lookup: Dict[Tuple[int, int, int, int], List[TileInfo]] = field(default_factory=dict)

    @staticmethod
    def from_tiles(tiles: List[TileInfo]) -> "ExperimentGrid":
        grid = ExperimentGrid()
        grid.timepoints = _unique_sorted(t.timepoint for t in tiles)
        grid.ix_positions = _unique_sorted(t.ix for t in tiles)
        grid.iy_positions = _unique_sorted(t.iy for t in tiles)
        grid.channels = _unique_sorted(t.channel for t in tiles)
        grid.c_indices = _unique_sorted(t.c_idx for t in tiles)
        for t in tiles:
            key = (t.timepoint, t.ix, t.iy, t.c_idx)
            grid.lookup.setdefault(key, []).append(t)
        return grid

    def get_tiles(self, tp: int, ix: int, iy: int, c_idx: int) -> List[TileInfo]:
        return self.lookup.get((tp, ix, iy, c_idx), [])

    def get_single(self, tp: int, ix: int, iy: int, c_idx: int) -> Optional[TileInfo]:
        tiles = self.get_tiles(tp, ix, iy, c_idx)
        return tiles[0] if tiles else None


def _read_tile(info: TileInfo) -> np.ndarray:
    return tif.imread(info.filepath)


# ---------------------------------------------------------------------------
# Focus measure / IO helpers
# ---------------------------------------------------------------------------

def _is_rgb(frame: np.ndarray) -> bool:
    return frame.ndim == 3 and frame.shape[2] in (3, 4)


_4GB = 4 * 1024 ** 3


def _imwrite_auto(fpath: str, arr: np.ndarray, **kwargs):
    """Write a TIFF, upgrading to BigTIFF when the array exceeds 4 GB."""
    if arr.nbytes > _4GB:
        kwargs.pop("imagej", None)
        kwargs["bigtiff"] = True
    tif.imwrite(fpath, arr, **kwargs)


def _save_rgb_from_multichannel(src_path: str, out_path: str, percentile=(1.0, 99.9)) -> bool:
    """Normalise a 3-channel stitched TIFF to an 8-bit RGB TIFF."""
    img = tif.imread(src_path)
    while img.ndim > 3:
        img = img[0]
    if img.ndim == 2:
        return False
    if img.ndim == 3 and img.shape[0] not in (3, 4):
        return False
    n_ch = min(img.shape[0], 3)
    channels = []
    for c in range(n_ch):
        ch = img[c].astype(np.float32)
        lo = float(np.percentile(ch, percentile[0]))
        hi = float(np.percentile(ch, percentile[1]))
        if hi > lo:
            ch = np.clip((ch - lo) / (hi - lo), 0.0, 1.0)
        else:
            ch = np.zeros_like(ch)
        channels.append((ch * 255).astype(np.uint8))
    rgb = np.stack(channels, axis=-1)
    tif.imwrite(out_path, rgb, photometric="rgb", compression="zlib")
    return True


def _focus_measure(frame: np.ndarray) -> float:
    """Normalised Laplacian variance focus measure (higher = sharper)."""
    if _is_rgb(frame):
        f = (0.299 * frame[:, :, 0] + 0.587 * frame[:, :, 1] + 0.114 * frame[:, :, 2]).astype(np.float32)
    else:
        f = frame.astype(np.float32)
    lap = (4.0 * f[1:-1, 1:-1]
           - f[:-2, 1:-1]
           - f[2:, 1:-1]
           - f[1:-1, :-2]
           - f[1:-1, 2:])
    mean_intensity = float(np.mean(f)) + 1e-6
    return float(np.var(lap)) / (mean_intensity ** 2)


# ---------------------------------------------------------------------------
# Mode 1: Composite stack (per position, for napari)
# ---------------------------------------------------------------------------

def build_composite_stacks(grid: ExperimentGrid, out_dir: str) -> List[str]:
    """Per (ix, iy): build a TCZYX composite stack for napari."""
    print("\n=== Building composite stacks (napari) ===")
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []

    xy_positions = sorted(set((t.ix, t.iy)
                              for tiles in grid.lookup.values()
                              for t in tiles))

    for pos_idx, (ix, iy) in enumerate(xy_positions):
        all_z_tiles = []
        for ci in grid.c_indices:
            for tp in grid.timepoints:
                tiles = grid.get_tiles(tp, ix, iy, ci)
                if tiles:
                    all_z_tiles.extend(tiles)
                    break
        if not all_z_tiles:
            continue
        nZ = max(len(grid.get_tiles(tp, ix, iy, ci))
                 for tp in grid.timepoints for ci in grid.c_indices)

        sample = _read_tile(all_z_tiles[0])
        h, w = sample.shape[:2]
        dtype = sample.dtype

        nT = len(grid.timepoints)
        nC = len(grid.c_indices)
        is_rgb = _is_rgb(sample)

        if is_rgb:
            nS = sample.shape[2]
            stack = np.zeros((nT, nZ, nC, h, w, nS), dtype=dtype)
        else:
            stack = np.zeros((nT, nZ, nC, h, w), dtype=dtype)

        for it, tp in enumerate(grid.timepoints):
            for ic, ci in enumerate(grid.c_indices):
                z_tiles = sorted(grid.get_tiles(tp, ix, iy, ci), key=lambda t: t.z)
                for iz, tile in enumerate(z_tiles):
                    frame = _read_tile(tile)
                    stack[it, iz, ic] = frame[:h, :w]

        fname = f"composite_ix{ix:03d}_iy{iy:03d}.ome.tif"
        fpath = os.path.join(out_dir, fname)

        if is_rgb:
            metadata = {"axes": "TZCYXS", "Channel": {"Name": grid.channels}}
            _imwrite_auto(fpath, stack, photometric="rgb", metadata=metadata)
        else:
            metadata = {"axes": "TZCYX", "Channel": {"Name": grid.channels}}
            _imwrite_auto(fpath, stack, imagej=True, metadata=metadata)
        written.append(fpath)
        print(f"  [{pos_idx+1}/{len(xy_positions)}] {fname}  "
              f"shape={stack.shape}  dtype={dtype}")
    return written


# ---------------------------------------------------------------------------
# Mode 2: Stitched OME-TIFF (per channel, for Fiji)
# ---------------------------------------------------------------------------

def _compute_canvas_from_grid(grid: ExperimentGrid, h: int, w: int):
    nCols = len(grid.ix_positions)
    nRows = len(grid.iy_positions)
    canvas_h = nRows * h
    canvas_w = nCols * w

    ix_seq = {v: i for i, v in enumerate(grid.ix_positions)}
    iy_seq = {v: i for i, v in enumerate(grid.iy_positions)}

    offset_map = {}
    for ix in grid.ix_positions:
        for iy in grid.iy_positions:
            col_px = ix_seq[ix] * w
            row_px = iy_seq[iy] * h
            offset_map[(ix, iy)] = (row_px, col_px)

    return canvas_h, canvas_w, offset_map


def _channel_c_idx(grid: ExperimentGrid, ch_name: str) -> Optional[int]:
    for tile_list in grid.lookup.values():
        for t in tile_list:
            if t.channel == ch_name:
                return t.c_idx
    return None


def _mip_or_first(tiles: List[TileInfo]) -> np.ndarray:
    if len(tiles) == 1:
        return _read_tile(tiles[0])
    frames = [_read_tile(t) for t in tiles]
    return np.max(np.stack(frames, axis=0), axis=0)


def build_stitched_tiffs(grid: ExperimentGrid, out_dir: str) -> List[str]:
    """Per channel x timepoint: stitch all XY positions (MIP over Z per position)."""
    print("\n=== Building stitched OME-TIFFs (Fiji) ===")
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []

    first_tile_list = next(iter(grid.lookup.values()))
    sample = _read_tile(first_tile_list[0])
    h, w = sample.shape[:2]
    dtype = sample.dtype
    is_rgb = _is_rgb(sample)

    canvas_h, canvas_w, offset_map = _compute_canvas_from_grid(grid, h, w)
    total = len(grid.channels) * len(grid.timepoints)
    count = 0

    for ch_name in grid.channels:
        ci = _channel_c_idx(grid, ch_name)
        if ci is None:
            continue
        for tp in grid.timepoints:
            count += 1
            if is_rgb:
                canvas = np.zeros((canvas_h, canvas_w, sample.shape[2]), dtype=dtype)
            else:
                canvas = np.zeros((canvas_h, canvas_w), dtype=dtype)
            placed = 0
            for ix in grid.ix_positions:
                for iy in grid.iy_positions:
                    tiles = grid.get_tiles(tp, ix, iy, ci)
                    if not tiles:
                        continue
                    frame = _mip_or_first(sorted(tiles, key=lambda t: t.z))
                    row, col = offset_map[(ix, iy)]
                    fh, fw = frame.shape[:2]
                    canvas[row:row+fh, col:col+fw] = frame[:h, :w]
                    placed += 1
            if placed == 0:
                continue
            fname = f"stitched_{ch_name}_t{tp:04d}.ome.tif"
            fpath = os.path.join(out_dir, fname)
            if is_rgb:
                _imwrite_auto(fpath, canvas, photometric="rgb", compression="zlib")
            else:
                _imwrite_auto(fpath, canvas, compression="zlib")
            written.append(fpath)
            print(f"  [{count}/{total}] {fname}  canvas={canvas.shape}  tiles={placed}")
    return written


# ---------------------------------------------------------------------------
# Mode 3: MIP per XY -> stitch
# ---------------------------------------------------------------------------

def _compute_mip(grid: ExperimentGrid, ix: int, iy: int,
                 c_idx: int, tp: int) -> Optional[np.ndarray]:
    tiles = grid.get_tiles(tp, ix, iy, c_idx)
    if not tiles:
        return None
    frames = [_read_tile(t) for t in sorted(tiles, key=lambda t: t.z)]
    return np.max(np.stack(frames, axis=0), axis=0)


def build_mip_stitched(grid: ExperimentGrid, out_dir: str) -> List[str]:
    """Per channel x timepoint: per-position MIP over Z, then stitch."""
    print("\n=== Building MIP-stitched images (Fiji) ===")
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []

    first_tile_list = next(iter(grid.lookup.values()))
    sample = _read_tile(first_tile_list[0])
    h, w = sample.shape[:2]
    dtype = sample.dtype
    is_rgb = _is_rgb(sample)

    canvas_h, canvas_w, offset_map = _compute_canvas_from_grid(grid, h, w)

    for ch_name in grid.channels:
        ci = _channel_c_idx(grid, ch_name)
        if ci is None:
            continue
        for tp in grid.timepoints:
            if is_rgb:
                canvas = np.zeros((canvas_h, canvas_w, sample.shape[2]), dtype=dtype)
            else:
                canvas = np.zeros((canvas_h, canvas_w), dtype=dtype)
            placed = 0
            for ix in grid.ix_positions:
                for iy in grid.iy_positions:
                    mip = _compute_mip(grid, ix, iy, ci, tp)
                    if mip is None:
                        continue
                    row, col = offset_map[(ix, iy)]
                    fh, fw = mip.shape[:2]
                    canvas[row:row+fh, col:col+fw] = mip[:h, :w]
                    placed += 1
            if placed == 0:
                continue
            fname = f"mip_stitched_{ch_name}_t{tp:04d}.ome.tif"
            fpath = os.path.join(out_dir, fname)
            if is_rgb:
                _imwrite_auto(fpath, canvas, photometric="rgb", compression="zlib")
            else:
                _imwrite_auto(fpath, canvas, compression="zlib")
            written.append(fpath)
            print(f"  {fname}  canvas={canvas.shape}  tiles={placed}")
    return written


# ---------------------------------------------------------------------------
# Mode 4: MIP composite (merge channels into napari composite)
# ---------------------------------------------------------------------------

def build_mip_composite(grid: ExperimentGrid, out_dir: str) -> List[str]:
    """Per-channel MIP-stitched canvases merged into a multi-channel composite."""
    print("\n=== Building MIP composite (napari) ===")
    os.makedirs(out_dir, exist_ok=True)

    first_tile_list = next(iter(grid.lookup.values()))
    sample = _read_tile(first_tile_list[0])
    h, w = sample.shape[:2]
    dtype = sample.dtype
    is_rgb = _is_rgb(sample)

    canvas_h, canvas_w, offset_map = _compute_canvas_from_grid(grid, h, w)

    nT = len(grid.timepoints)
    nC = len(grid.channels)

    if is_rgb:
        nS = sample.shape[2]
        stack = np.zeros((nT, 1, nC, canvas_h, canvas_w, nS), dtype=dtype)
    else:
        stack = np.zeros((nT, 1, nC, canvas_h, canvas_w), dtype=dtype)

    for ic, ch_name in enumerate(grid.channels):
        ci = _channel_c_idx(grid, ch_name)
        if ci is None:
            continue
        for it, tp in enumerate(grid.timepoints):
            for ix in grid.ix_positions:
                for iy in grid.iy_positions:
                    mip = _compute_mip(grid, ix, iy, ci, tp)
                    if mip is None:
                        continue
                    row, col = offset_map[(ix, iy)]
                    fh, fw = mip.shape[:2]
                    stack[it, 0, ic, row:row+fh, col:col+fw] = mip[:h, :w]

    fname = "mip_composite.ome.tif"
    fpath = os.path.join(out_dir, fname)

    if is_rgb:
        metadata = {"axes": "TZCYXS", "Channel": {"Name": grid.channels}}
        _imwrite_auto(fpath, stack, photometric="rgb", metadata=metadata)
    else:
        metadata = {"axes": "TZCYX", "Channel": {"Name": grid.channels}}
        _imwrite_auto(fpath, stack, imagej=True, metadata=metadata)
    print(f"  {fname}  shape={stack.shape}  dtype={dtype}")
    return [fpath]


# ---------------------------------------------------------------------------
# Mode 5: Best-focus plane selection
# ---------------------------------------------------------------------------

def _best_focus_frame(grid: ExperimentGrid, ix: int, iy: int,
                      c_idx: int, tp: int) -> Optional[np.ndarray]:
    best_frame = None
    best_score = -1.0
    for tile in sorted(grid.get_tiles(tp, ix, iy, c_idx), key=lambda t: t.z):
        frame = _read_tile(tile)
        score = _focus_measure(frame)
        if score > best_score:
            best_score = score
            best_frame = frame
    return best_frame


def build_best_focus_stitched(grid: ExperimentGrid, out_dir: str) -> List[str]:
    """Per channel x timepoint: select sharpest Z-plane per XY, then stitch."""
    print("\n=== Building best-focus stitched images (post-proc. autofocus) ===")
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []

    first_tile_list = next(iter(grid.lookup.values()))
    sample = _read_tile(first_tile_list[0])
    h, w = sample.shape[:2]
    dtype = sample.dtype
    is_rgb = _is_rgb(sample)

    canvas_h, canvas_w, offset_map = _compute_canvas_from_grid(grid, h, w)

    for ch_name in grid.channels:
        ci = _channel_c_idx(grid, ch_name)
        if ci is None:
            continue
        for tp in grid.timepoints:
            if is_rgb:
                canvas = np.zeros((canvas_h, canvas_w, sample.shape[2]), dtype=dtype)
            else:
                canvas = np.zeros((canvas_h, canvas_w), dtype=dtype)
            placed = 0
            for ix in grid.ix_positions:
                for iy in grid.iy_positions:
                    frame = _best_focus_frame(grid, ix, iy, ci, tp)
                    if frame is None:
                        continue
                    row, col = offset_map[(ix, iy)]
                    fh, fw = frame.shape[:2]
                    canvas[row:row+fh, col:col+fw] = frame[:h, :w]
                    placed += 1
            if placed == 0:
                continue
            fname = f"bestfocus_stitched_{ch_name}_t{tp:04d}.ome.tif"
            fpath = os.path.join(out_dir, fname)
            if is_rgb:
                _imwrite_auto(fpath, canvas, photometric="rgb", compression="zlib")
            else:
                _imwrite_auto(fpath, canvas, compression="zlib")
            written.append(fpath)
            print(f"  {fname}  canvas={canvas.shape}  tiles={placed}")
    return written


# ---------------------------------------------------------------------------
# Mode 6: Timelapse concatenation
# ---------------------------------------------------------------------------

def _get_frame_for_timepoint(
    grid: ExperimentGrid, ix: int, iy: int, c_idx: int, tp: int, use_mip: bool
) -> Optional[np.ndarray]:
    tiles = sorted(grid.get_tiles(tp, ix, iy, c_idx), key=lambda t: t.z)
    if not tiles:
        return None
    if use_mip and len(tiles) > 1:
        return np.max(np.stack([_read_tile(t) for t in tiles], axis=0), axis=0)
    if len(tiles) == 1:
        return _read_tile(tiles[0])
    best, best_score = None, -1.0
    for t in tiles:
        f = _read_tile(t)
        s = _focus_measure(f)
        if s > best_score:
            best_score, best = s, f
    return best


def build_timelapse(grid: ExperimentGrid, out_dir: str, use_mip: bool = False) -> List[str]:
    """Concatenate same (ix, iy, channel) across timepoints into a TCYX hyperstack."""
    label = "mip" if use_mip else "bestfocus"
    print(f"\n=== Building timelapse stacks (Z={label}) ===")
    os.makedirs(out_dir, exist_ok=True)

    xy_positions = sorted(
        set((t.ix, t.iy) for tiles in grid.lookup.values() for t in tiles)
    )

    def _find_sample() -> Optional[np.ndarray]:
        for tiles in grid.lookup.values():
            if tiles:
                return _read_tile(tiles[0])
        return None

    sample = _find_sample()
    if sample is None:
        print("  No tiles found - skipping")
        return []
    h, w = sample.shape[:2]
    dtype = sample.dtype

    nT = len(grid.timepoints)
    nC = len(grid.c_indices)
    single_pos = len(xy_positions) == 1

    if single_pos:
        ix, iy = xy_positions[0]
        stack = np.zeros((nT, nC, h, w), dtype=dtype)
        for it, tp in enumerate(grid.timepoints):
            for ic, ci in enumerate(grid.c_indices):
                frame = _get_frame_for_timepoint(grid, ix, iy, ci, tp, use_mip)
                if frame is not None:
                    stack[it, ic] = frame[:h, :w]

        fname = f"timelapse_{label}.ome.tif"
        fpath = os.path.join(out_dir, fname)
        tif.imwrite(
            fpath, stack, imagej=True,
            metadata={"axes": "TCYX", "Channel": {"Name": grid.channels}},
        )
        print(f"  {fname}  shape={stack.shape}  dtype={dtype}  "
              f"({nT} timepoints, {nC} channels)")
        return [fpath]
    else:
        _, _, offset_map = _compute_canvas_from_grid(grid, h, w)
        canvas_h = len(grid.iy_positions) * h
        canvas_w = len(grid.ix_positions) * w

        stack = np.zeros((nT, nC, canvas_h, canvas_w), dtype=dtype)
        for it, tp in enumerate(grid.timepoints):
            for ic, ci in enumerate(grid.c_indices):
                for ix, iy in xy_positions:
                    frame = _get_frame_for_timepoint(grid, ix, iy, ci, tp, use_mip)
                    if frame is None:
                        continue
                    row, col = offset_map[(ix, iy)]
                    fh, fw = frame.shape[:2]
                    stack[it, ic, row:row+fh, col:col+fw] = frame[:h, :w]

        fname = f"timelapse_stitched_{label}.ome.tif"
        fpath = os.path.join(out_dir, fname)
        tif.imwrite(
            fpath, stack, imagej=True,
            metadata={"axes": "TCYX", "Channel": {"Name": grid.channels}},
        )
        print(f"  {fname}  shape={stack.shape}  dtype={dtype}  "
              f"({nT} timepoints, {nC} channels, {len(xy_positions)} positions)")
        return [fpath]


# ---------------------------------------------------------------------------
# Minimal ashlar-compatible reader (fallback)
# ---------------------------------------------------------------------------

class _NumpyMetadata:
    """Minimal ashlar Metadata backed by numpy arrays derived from TileInfo objects."""

    def __init__(self, positions_px, tile_size, pixel_size_um, num_channels, dtype):
        self._positions = np.asarray(positions_px, dtype=np.float64)
        self._size = np.array(tile_size)
        self._pixel_size = float(pixel_size_um)
        self._num_channels = int(num_channels)
        self._dtype = dtype

    @property
    def num_images(self):
        return len(self._positions)

    @property
    def num_channels(self):
        return self._num_channels

    @property
    def pixel_size(self):
        return self._pixel_size

    @property
    def positions(self):
        return self._positions

    @property
    def size(self):
        return self._size

    @property
    def pixel_dtype(self):
        return self._dtype


class _NumpyReader:
    """Minimal ashlar-compatible Reader backed by ImSwitch TileInfo file paths."""

    def __init__(self, metadata: _NumpyMetadata, tiles_dict: dict, is_rgb: bool = False):
        self._metadata = metadata
        self._tiles = tiles_dict
        self._is_rgb = is_rgb

    @property
    def metadata(self):
        return self._metadata

    def read(self, series, c):
        if self._is_rgb:
            c_orig, plane = divmod(c, 3)
            tile = self._tiles.get((series, c_orig))
            if tile is None:
                h, w = self._metadata.size
                return np.zeros((h, w), dtype=self._metadata.pixel_dtype)
            img = tif.imread(tile.filepath)
            return img[..., plane] if img.ndim == 3 else img
        tile = self._tiles.get((series, c))
        if tile is None:
            h, w = self._metadata.size
            return np.zeros((h, w), dtype=self._metadata.pixel_dtype)
        img = tif.imread(tile.filepath)
        if img.ndim == 3 and img.shape[2] in (3, 4):
            img = np.dot(img[..., :3], [0.299, 0.587, 0.114]).astype(np.uint16)
        return img


def _build_numpy_reader(
    grid: "ExperimentGrid",
    tp: int,
    c_indices: List[int],
    pixel_size_um: float,
) -> Optional["_NumpyReader"]:
    """Build a _NumpyReader for one timepoint directly from the ExperimentGrid."""
    positions_px: List[Tuple[float, float]] = []
    tiles_dict: dict = {}
    ref_size: Optional[Tuple[int, int]] = None
    ref_dtype = None
    is_rgb: bool = False
    pos_idx = 0

    for ix in grid.ix_positions:
        for iy in grid.iy_positions:
            has_any = any(grid.get_tiles(tp, ix, iy, ci) for ci in c_indices)
            if not has_any:
                continue

            ref_tile = None
            for ci in c_indices:
                z_tiles = grid.get_tiles(tp, ix, iy, ci)
                if z_tiles:
                    ref_tile = z_tiles[0]
                    break
            scale = 1.0 / (1000.0 * pixel_size_um)
            y_px = ref_tile.y * scale
            x_px = ref_tile.x * scale
            positions_px.append((y_px, x_px))

            for c_local, ci in enumerate(c_indices):
                z_tiles = grid.get_tiles(tp, ix, iy, ci)
                if not z_tiles:
                    continue
                best = _select_best_z_tile(sorted(z_tiles, key=lambda t: t.z))
                tiles_dict[(pos_idx, c_local)] = best

                if ref_size is None:
                    img = tif.imread(best.filepath)
                    is_rgb = img.ndim == 3 and img.shape[2] in (3, 4)
                    ref_size = img.shape[:2]
                    ref_dtype = img[..., 0].dtype if is_rgb else img.dtype

            pos_idx += 1

    if not positions_px:
        return None

    min_y = min(p[0] for p in positions_px)
    min_x = min(p[1] for p in positions_px)
    positions_px = [(y - min_y, x - min_x) for y, x in positions_px]

    num_channels = len(c_indices) * (3 if is_rgb else 1)
    meta = _NumpyMetadata(
        positions_px=positions_px,
        tile_size=ref_size,
        pixel_size_um=pixel_size_um,
        num_channels=num_channels,
        dtype=ref_dtype,
    )
    return _NumpyReader(meta, tiles_dict, is_rgb=is_rgb)


# ---------------------------------------------------------------------------
# Mode 7: Ashlar-based stitching with sub-pixel alignment
# ---------------------------------------------------------------------------

def _select_best_z_tile(tiles: List[TileInfo]) -> TileInfo:
    if len(tiles) == 1:
        return tiles[0]
    best_tile, best_score = tiles[0], -1.0
    for t in tiles:
        img = tif.imread(t.filepath)
        score = _focus_measure(img)
        if score > best_score:
            best_score, best_tile = score, t
    return best_tile


def build_ashlar_stitched(
    grid: ExperimentGrid,
    out_dir: str,
    pixel_size: float = 1.0,
    maximum_shift: float = 50.0,
    align_channel: int = 0,
) -> List[str]:
    """Stitch tiles per timepoint using ashlarUC2's edge aligner."""
    process_images = None
    build_imswitch_reader = None

    for _pkg in ("ashlarUC2", "ashlar"):
        try:
            _mod = __import__(f"{_pkg}.scripts.ashlar", fromlist=["process_images"])
            process_images = getattr(_mod, "process_images", None)
            build_imswitch_reader = getattr(_mod, "build_imswitch_reader", None)
            if process_images is not None:
                print(f"  Using {_pkg} (build_imswitch_reader={'yes' if build_imswitch_reader else 'no'})")
                break
        except Exception as _exc:
            print(f"  Could not import {_pkg}: {_exc}")

    if process_images is None:
        raise RuntimeError(
            "Neither ashlarUC2 nor ashlar could be imported. "
            "Install with: pip install ashlarUC2"
        )

    print("\n=== Building ashlar-stitched OME-TIFFs (sub-pixel alignment) ===")
    print(f"  pixel_size={pixel_size} um  maximum_shift={maximum_shift} um  "
          f"align_channel={align_channel}")
    os.makedirs(out_dir, exist_ok=True)

    files_written: List[str] = []

    for tp in grid.timepoints:
        print(f"\n  --- Timepoint {tp} ---")

        selected_paths: List[str] = []
        for ix in grid.ix_positions:
            for iy in grid.iy_positions:
                for ci in grid.c_indices:
                    z_tiles = grid.get_tiles(tp, ix, iy, ci)
                    if not z_tiles:
                        continue
                    best = _select_best_z_tile(sorted(z_tiles, key=lambda t: t.z))
                    selected_paths.append(best.filepath)

        if not selected_paths:
            print(f"  Skipping timepoint {tp}: no tiles found.")
            continue

        n_channels = len(grid.c_indices)
        n_positions = len(grid.ix_positions) * len(grid.iy_positions)
        print(f"  {len(selected_paths)} tiles selected  "
              f"({n_positions} XY positions x {n_channels} channel(s))")

        out_file = os.path.join(out_dir, f"ashlar_stitched_t{tp:04d}.ome.tif")
        print(f"  Output -> {os.path.basename(out_file)}")

        if build_imswitch_reader is not None:
            try:
                reader = build_imswitch_reader(selected_paths, pixel_size=pixel_size)
                filepaths_arg = [reader]
            except Exception as exc:
                print(f"  WARNING: build_imswitch_reader failed ({exc}), falling back to numpy reader")
                import traceback
                traceback.print_exc()
                reader = _build_numpy_reader(grid, tp, grid.c_indices, pixel_size)
                if reader is None:
                    print(f"  Skipping timepoint {tp}: no tiles for reader construction.")
                    continue
                filepaths_arg = [reader]
        else:
            print("  build_imswitch_reader not available - using built-in numpy reader")
            reader = _build_numpy_reader(grid, tp, grid.c_indices, pixel_size)
            if reader is None:
                print(f"  Skipping timepoint {tp}: no tiles for reader construction.")
                continue
            filepaths_arg = [reader]

        _meta = reader.metadata
        _pos = np.asarray(_meta.positions, dtype=float)
        _sz = np.asarray(_meta.size, dtype=float)
        _ps = float(_meta.pixel_size)
        print(f"  Tile size: {tuple(int(v) for v in _sz)} px  "
              f"pixel_size: {_ps} um/px  FOV: {_sz * _ps} um")
        if len(_pos) > 1:
            _min_ov = np.inf
            _n_overlapping = 0
            for _ii in range(len(_pos)):
                for _jj in range(_ii + 1, len(_pos)):
                    _diff_px = np.abs(_pos[_jj] - _pos[_ii])
                    if _diff_px.sum() > 0 and np.all(_diff_px < _sz):
                        _ov = float(np.min(_sz - _diff_px))
                        _min_ov = min(_min_ov, _ov)
                        _n_overlapping += 1
            if _min_ov == np.inf:
                print(
                    "  ERROR: No tile pairs share any pixel overlap - ashlar requires "
                    "overlapping tiles for edge registration."
                )
                continue
            else:
                print(f"  Min expected tile overlap: {_min_ov:.1f} px  ({_n_overlapping} overlapping pair(s))")
                if _min_ov < 50:
                    print(f"  WARNING: Very small tile overlap ({_min_ov:.0f} px).")

        try:
            result = process_images(
                filepaths=filepaths_arg,
                output=out_file,
                align_channel=align_channel,
                flip_x=False,
                flip_y=False,
                flip_mosaic_x=False,
                flip_mosaic_y=False,
                output_channels=None,
                maximum_shift=maximum_shift,
                stitch_alpha=0.01,
                maximum_error=None,
                filter_sigma=0,
                pyramid=out_file.endswith(".ome.tif") or out_file.endswith(".ome.tiff"),
                tile_size=1024,
                ffp=None,
                dfp=None,
                barrel_correction=0,
                plates=False,
                quiet=False,
            )
        except (ValueError, Exception) as exc:
            _emsg = str(exc)
            if "high <= 0" in _emsg or "low >= high" in _emsg:
                print(f"  ERROR: Ashlar edge-registration failed ('{_emsg}') - possible overlap issue.")
            else:
                print(f"  ERROR during ashlar processing for tp={tp}: {exc}")
            import traceback
            traceback.print_exc()
            continue

        if result and result != 0:
            print(f"  WARNING: ashlar returned non-zero status {result} for tp={tp}")
        elif os.path.isfile(out_file):
            print(f"  Written: {out_file}")
            files_written.append(out_file)
            rgb_path = out_file[:-8] + "_rgb.tif" if out_file.endswith(".ome.tif") else out_file + "_rgb.tif"
            try:
                if _save_rgb_from_multichannel(out_file, rgb_path):
                    print(f"  RGB: {os.path.basename(rgb_path)}")
                    files_written.append(rgb_path)
            except Exception as _rgb_exc:
                print(f"  WARNING: RGB merge failed: {_rgb_exc}")
        else:
            print(f"  WARNING: ashlar reported success but output file is missing: {out_file}")

    print(f"\n  Ashlar outputs in: {out_dir}")
    if not files_written:
        print("  ERROR: No output files were written by ashlar.")
    return files_written


# ---------------------------------------------------------------------------
# Fiji TileConfiguration.txt
# ---------------------------------------------------------------------------

def write_tile_configuration(grid: ExperimentGrid, out_dir: str) -> List[str]:
    """Write Fiji-compatible TileConfiguration.txt files (one per channel/timepoint)."""
    print("\n=== Writing TileConfiguration.txt (Fiji) ===")
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []

    first_tile_list = next(iter(grid.lookup.values()))
    sample = _read_tile(first_tile_list[0])
    h, w = sample.shape[:2]

    _, _, offset_map = _compute_canvas_from_grid(grid, h, w)

    for ch_name in grid.channels:
        ci = _channel_c_idx(grid, ch_name)
        if ci is None:
            continue
        for tp in grid.timepoints:
            fname = f"TileConfiguration_{ch_name}_t{tp:04d}.txt"
            fpath = os.path.join(out_dir, fname)
            with open(fpath, "w") as f:
                f.write("# Define the number of dimensions we are working on\n")
                f.write("dim = 2\n\n")
                f.write("# Define the image coordinates\n")
                for ix in grid.ix_positions:
                    for iy in grid.iy_positions:
                        tiles = grid.get_tiles(tp, ix, iy, ci)
                        if not tiles:
                            continue
                        info = sorted(tiles, key=lambda t: t.z)[0]
                        row, col = offset_map[(ix, iy)]
                        rel_path = os.path.relpath(info.filepath, out_dir)
                        f.write(f"{rel_path}; ; ({col}, {row})\n")
            written.append(fpath)
            print(f"  {fname}")
    return written
