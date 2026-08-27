"""Tests for widgets.readnoise.ReadnoiseWidget's layer-selection logic.

Runs Qt in offscreen mode and uses a bare napari LayerList (no real Viewer /
GL canvas) so these stay fast and don't need a display.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

import napari.layers
from napari.components import LayerList
from qtpy.QtWidgets import QApplication, QTabWidget

from openuc2_processor.widgets.readnoise import ReadnoiseWidget


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeViewer:
    def __init__(self):
        self.layers = LayerList()


def _synthetic_stacks(n=6, size=16, seed=2):
    rng = np.random.default_rng(seed)
    fg = rng.uniform(500, 600, size=(n, size, size)).astype(np.float32)
    bg = rng.uniform(90, 110, size=(n, size, size)).astype(np.float32)
    return fg, bg


def test_defaults_pick_two_distinct_layers():
    viewer = _FakeViewer()
    fg, bg = _synthetic_stacks()
    viewer.layers.append(napari.layers.Image(fg, name="brightfield_stack"))
    viewer.layers.append(napari.layers.Image(bg, name="background_stack"))

    widget = ReadnoiseWidget(napari_viewer=viewer)

    assert widget.fg_combo.currentText() == "brightfield_stack"
    assert widget.bg_combo.currentText() == "background_stack"
    assert widget.fg_combo.currentText() != widget.bg_combo.currentText()


def test_run_populates_status_and_plots():
    viewer = _FakeViewer()
    fg, bg = _synthetic_stacks()
    viewer.layers.append(napari.layers.Image(fg, name="fg"))
    viewer.layers.append(napari.layers.Image(bg, name="bg"))

    widget = ReadnoiseWidget(napari_viewer=viewer)
    widget._on_run()

    assert "gain=" in widget.status.text()
    assert "Gain [e- / ADU]" in widget.results_edit.toPlainText()
    assert len(widget._plot_windows) == 1
    tabs = widget._plot_windows[0].findChild(QTabWidget)
    assert tabs is not None
    assert tabs.count() > 0
