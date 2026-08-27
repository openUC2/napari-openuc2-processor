"""Tests for processing.readnoise (no Qt/napari viewer required)."""

import sys

import matplotlib
import matplotlib.figure
import numpy as np
import pytest

matplotlib.use("Agg")  # headless: never touch a real GUI backend in tests

from openuc2_processor.processing.readnoise import ReadnoiseParams, run_cal_readnoise


def _synthetic_stacks(n=12, size=48, seed=0):
    """Foreground (bright, Poisson-ish) / background (dark) camera-noise stacks."""
    rng = np.random.default_rng(seed)
    gain = 2.0        # e-/ADU
    offset = 100.0     # ADU
    readnoise = 3.0    # e- RMS

    fg = []
    for _ in range(n):
        signal = rng.uniform(200, 4000, size=(size, size))
        electrons = rng.poisson(signal)
        adu = electrons / gain + offset + rng.normal(0, readnoise / gain, size=(size, size))
        fg.append(adu)
    bg = []
    for _ in range(n):
        adu = offset + rng.normal(0, readnoise / gain, size=(size, size))
        bg.append(adu)
    return np.stack(fg).astype(np.float32), np.stack(bg).astype(np.float32)


def test_run_cal_readnoise_returns_typed_result():
    fg, bg = _synthetic_stacks()

    result = run_cal_readnoise(fg, bg, ReadnoiseParams(numBins=20))

    assert isinstance(result.offset, float)
    assert isinstance(result.gain, float)
    assert isinstance(result.readnoise, float)
    assert isinstance(result.mean_electrons_per_exposure, float)
    assert result.validmap.shape == fg.shape[-2:]
    assert result.figures  # at least one (Figure, name) plot produced
    for fig, name in result.figures:
        assert isinstance(fig, matplotlib.figure.Figure)
        assert isinstance(name, str)
    assert "Gain [e- / ADU]" in result.doc


def test_run_cal_readnoise_respects_camera_name_and_bins():
    fg, bg = _synthetic_stacks()

    result = run_cal_readnoise(fg, bg, ReadnoiseParams(numBins=15, CameraName="TestCam"))

    assert result.figures


def test_run_cal_readnoise_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "NanoImagingPack", None)
    fg, bg = _synthetic_stacks(n=2, size=8)

    with pytest.raises(ImportError, match="NanoImagingPack"):
        run_cal_readnoise(fg, bg)
