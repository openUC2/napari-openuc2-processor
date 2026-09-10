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


def test_frame_transform_flip_and_rotate():
    import numpy as np

    arr = np.arange(6, dtype=np.uint16).reshape(2, 3)  # non-square
    try:
        engine.set_frame_transform(rotate=90)
        assert engine.frame_transform_active()
        assert engine._apply_frame_transform(arr).shape == (3, 2)  # dims swapped

        engine.set_frame_transform(flip_x=True)
        assert np.array_equal(engine._apply_frame_transform(arr), arr[:, ::-1])
    finally:
        engine.reset_frame_transform()

    assert not engine.frame_transform_active()
    # inactive transform is a no-op (returns the same array)
    assert engine._apply_frame_transform(arr) is arr


# ---------------------------------------------------------------------------
# Scan regions
# ---------------------------------------------------------------------------

def _tile(iterator, region="", x=0, y=0):
    from openuc2_processor.processing.engine import TileInfo
    return TileInfo(filepath=f"/d/{region}_{iterator}.tif", timestamp="20260910_120000",
                    x=x, y=y, z=0, c_idx=0, channel="LED", iterator=iterator,
                    power=0, region=region)


def _protocol(tmp_path, regions, n=9):
    import json
    data = {"snake_tiles": [
        [{"iterator": i, "iX": i % 3, "iY": i // 3, "region_id": r} for i in range(n)]
        for r in regions
    ]}
    path = tmp_path / "run_protocol.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_region_is_parsed_from_the_filename_and_is_optional():
    from openuc2_processor.processing.engine import parse_filename
    with_region = parse_filename(
        "/d/t20260910_120000_rarea0_x1000_y2000_z0_c0_LED_i0003_p100.tif")
    without = parse_filename(
        "/d/t20260910_120000_x1000_y2000_z0_c0_LED_i0003_p100.tif")
    assert with_region.region == "area0"
    assert with_region.iterator == 3 and with_region.x == 1000
    assert without.region == ""          # pre-region data still parses
    assert without.iterator == 3 and without.x == 1000


def test_each_region_gets_its_own_grid_origin(tmp_path):
    """Iterators restart per region; one flat map made them overwrite."""
    from openuc2_processor.processing.engine import assign_grid_indices
    tiles = [_tile(i, region=r, x=i * 100)
             for r in ("area0", "area1") for i in range(9)]
    assign_grid_indices(tiles, _protocol(tmp_path, ["area_0", "area_1"]))

    for region in ("area0", "area1"):
        placed = [(t.ix, t.iy) for t in tiles if t.region == region]
        assert sorted(placed) == [(x, y) for x in range(3) for y in range(3)]


def test_a_missing_tile_does_not_shift_the_rest(tmp_path):
    """Rank matching paired the Nth position with the Nth JSON entry, so one
    dropped tile moved every position after it."""
    from openuc2_processor.processing.engine import assign_grid_indices
    tiles = [_tile(i, region="area0", x=i * 100) for i in range(9) if i != 4]
    assign_grid_indices(tiles, _protocol(tmp_path, ["area_0"]))

    by_iterator = {t.iterator: (t.ix, t.iy) for t in tiles}
    assert by_iterator[5] == (2, 1)   # keeps its own place
    assert by_iterator[8] == (2, 2)
    assert 4 not in by_iterator


def test_tiles_from_another_run_fall_back_instead_of_placing_them_wrongly(tmp_path, capsys):
    from openuc2_processor.processing.engine import assign_grid_indices
    tiles = [_tile(i, region="area0", x=i * 100) for i in range(20)]
    assign_grid_indices(tiles, _protocol(tmp_path, ["area_0"], n=9))
    assert "not present in the protocol" in capsys.readouterr().out
    assert all(t.ix >= 0 and t.iy >= 0 for t in tiles)


def test_group_by_region_keeps_first_seen_order():
    from openuc2_processor.processing.engine import group_by_region
    tiles = [_tile(0, "b"), _tile(1, "a"), _tile(2, "b")]
    assert list(group_by_region(tiles)) == ["b", "a"]
