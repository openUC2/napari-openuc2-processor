"""Engine + registry tests on synthetic tiles (no napari/Qt needed)."""

import os

from openuc2_processor.processing import ProcessParams, engine, run_processors
from openuc2_processor.processing.registry import PROCESSORS


def test_parse_filename_roundtrip():
    info = engine.parse_filename(
        "t20260101_000000_x1000_y2000_z0_c1_GFP_i5_p10.tif"
    )
    assert info is not None
    assert (info.x, info.y, info.c_idx, info.channel, info.iterator) == (
        1000, 2000, 1, "GFP", 5,
    )


def test_discover_and_grid(tiles_2x2):
    tiles = engine.discover_any(tiles_2x2)
    assert len(tiles) == 4
    grid = engine.ExperimentGrid.from_tiles(tiles)
    assert len(grid.ix_positions) == 2
    assert len(grid.iy_positions) == 2
    assert grid.channels == ["BF"]


def test_composite_one_file_per_position(tiles_2x2, tmp_path):
    tiles = engine.discover_any(tiles_2x2)
    grid = engine.ExperimentGrid.from_tiles(tiles)
    out = os.path.join(str(tmp_path), "composite")
    written = engine.build_composite_stacks(grid, out)
    assert len(written) == 4  # one per (ix, iy)
    assert all(os.path.isfile(p) for p in written)


def test_mip_stitched_single_canvas(tiles_2x2, tmp_path):
    tiles = engine.discover_any(tiles_2x2)
    grid = engine.ExperimentGrid.from_tiles(tiles)
    written = engine.build_mip_stitched(grid, os.path.join(str(tmp_path), "mip"))
    assert len(written) == 1
    assert os.path.isfile(written[0])


def test_run_processors_multi(tiles_2x1_2c, tmp_path):
    out = os.path.join(str(tmp_path), "converted")
    results = run_processors(
        tiles_2x1_2c,
        keys=["mip", "tile-config", "composite"],
        params=ProcessParams(output_dir=out),
    )
    assert set(results) == {"mip", "tile-config", "composite"}
    # mip: 2 channels x 1 timepoint -> 2 files
    assert len(results["mip"]) == 2
    # composite: 2 positions -> 2 files
    assert len(results["composite"]) == 2
    # all output files live under the chosen output dir
    for paths in results.values():
        for p in paths:
            assert p.startswith(out)
            assert os.path.isfile(p)


def test_registry_has_all_modes():
    expected = {
        "composite", "stitch", "mip", "mip-composite", "focus",
        "tile-config", "timelapse", "timelapse-mip", "ashlar",
    }
    assert expected.issubset(set(PROCESSORS))
