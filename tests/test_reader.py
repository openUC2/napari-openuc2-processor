"""CLI reader dispatch tests (no napari/Qt required)."""

from openuc2_processor._reader import napari_get_reader, reader_function


def test_get_reader_accepts_known_sources(tmp_path):
    assert napari_get_reader(str(tmp_path)) is not None        # existing path
    assert napari_get_reader("13457227.zarr") is not None      # record id
    assert napari_get_reader("http://host/x.ome.zarr") is not None
    # list form (napari may pass a list of paths)
    assert napari_get_reader([str(tmp_path)]) is not None


def test_get_reader_rejects_unknown():
    assert napari_get_reader("this is not valid") is None
    assert napari_get_reader(12345) is None
    assert napari_get_reader("") is None


def test_reader_function_returns_no_layer_sentinel():
    # Headless: napari.current_viewer() is None (or napari absent) -> no widget,
    # but the [(None,)] sentinel must still be returned so napari reports success.
    assert reader_function("13457227.zarr") == [(None,)]
