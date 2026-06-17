"""Shared test fixtures: synthesize ImSwitch-style tiles."""

import os

import numpy as np
import pytest
import tifffile as tif


def _tile_name(x, y, z, c_idx, channel, it, power=0, ts="20260101_000000"):
    return f"t{ts}_x{x}_y{y}_z{z}_c{c_idx}_{channel}_i{it}_p{power}.tif"


def make_tiles(base_dir, nx=2, ny=2, channels=("BF",), nz=1, nt=1,
               size=16, step_um=1):
    """Create a synthetic tiles/ tree and return its path.

    Layout: ``base_dir/timepoint_XXXX/<tile>.tif`` with filenames following the
    ImSwitch convention (X/Y/Z in microns*1000).
    """
    tiles_dir = os.path.join(str(base_dir), "tiles")
    it = 0
    for tp in range(nt):
        tp_dir = os.path.join(tiles_dir, f"timepoint_{tp:04d}")
        os.makedirs(tp_dir, exist_ok=True)
        for iy in range(ny):
            for ix in range(nx):
                for z in range(nz):
                    for c_idx, ch in enumerate(channels):
                        arr = np.full((size, size), it % 255, dtype=np.uint16)
                        fname = _tile_name(
                            x=ix * step_um * 1000,
                            y=iy * step_um * 1000,
                            z=z,
                            c_idx=c_idx,
                            channel=ch,
                            it=it,
                        )
                        tif.imwrite(os.path.join(tp_dir, fname), arr)
                        it += 1
    return tiles_dir


@pytest.fixture
def tiles_2x2(tmp_path):
    return make_tiles(tmp_path, nx=2, ny=2, channels=("BF",), nz=1, nt=1)


@pytest.fixture
def tiles_2x1_2c(tmp_path):
    return make_tiles(tmp_path, nx=2, ny=1, channels=("BF", "GFP"), nz=1, nt=1)
