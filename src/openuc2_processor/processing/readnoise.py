"""Photon-transfer / read-noise calibration via NanoImagingPack's cal_readnoise.

Fits a straight line through the per-pixel mean/variance plot of a
foreground (bright) and background (dark) image series to recover the
camera's offset, gain and read noise. This module is a thin, GUI-free
wrapper so the widget layer doesn't need to know about the NanoImagingPack
import or its raw tuple return value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class ReadnoiseParams:
    """User-tunable subset of ``NanoImagingPack.cal_readnoise``'s keyword args."""
    numBins: int = 100
    validRange: Optional[Tuple[float, float]] = None
    linearity_range: Optional[Tuple[float, float]] = None
    histRange: Optional[Tuple[float, float]] = None
    CameraName: Optional[str] = None
    correctBrightness: bool = True
    correctOffsetDrift: bool = True
    exclude_hot_cold_pixels: bool = True
    noisy_pixel_percentile: float = 98.0
    brightness_blurring: bool = True
    plotWithBgOffset: bool = True
    plotHist: bool = False
    check_bg: bool = False
    saturationImage: bool = False
    exportpath: Optional[str] = None
    exportFormat: str = "png"


@dataclass
class ReadnoiseResult:
    """Typed view of ``cal_readnoise``'s ``(offset, gain, readnoise, mean_el,
    validmap, figures, doc)`` return tuple."""
    offset: float                      # background level [ADU]
    gain: float                        # conversion factor [e-/ADU]
    readnoise: float                   # RMS read noise [e-]
    mean_electrons_per_exposure: float
    validmap: np.ndarray
    figures: List[Tuple[Any, str]]     # (matplotlib Figure, name) pairs
    doc: Dict[str, Tuple[str, str]]    # label -> (value, description)


def run_cal_readnoise(
    fg: np.ndarray, bg: np.ndarray, params: Optional[ReadnoiseParams] = None
) -> ReadnoiseResult:
    """Run NanoImagingPack's photon-transfer calibration on *fg* / *bg* stacks.

    ``fg`` is a foreground/bright image series and ``bg`` a background/dark
    series captured under identical camera settings; both are expected to
    have shape ``(n_frames, height, width)``.
    """
    try:
        import NanoImagingPack as nip
    except ImportError as exc:
        raise ImportError(
            "Read-noise calibration requires the 'NanoImagingPack' package. "
            "Install it with: pip install NanoImagingPack"
        ) from exc

    params = params or ReadnoiseParams()
    offset, gain, readnoise, mean_el, validmap, figures, doc = nip.cal_readnoise(
        np.asarray(fg),
        np.asarray(bg),
        numBins=params.numBins,
        validRange=list(params.validRange) if params.validRange else None,
        linearity_range=list(params.linearity_range) if params.linearity_range else None,
        histRange=list(params.histRange) if params.histRange else None,
        CameraName=params.CameraName or None,
        correctBrightness=params.correctBrightness,
        correctOffsetDrift=params.correctOffsetDrift,
        exclude_hot_cold_pixels=params.exclude_hot_cold_pixels,
        noisy_pixel_percentile=params.noisy_pixel_percentile,
        doPlot=True,
        exportpath=params.exportpath or None,
        exportFormat=params.exportFormat,
        brightness_blurring=params.brightness_blurring,
        plotWithBgOffset=params.plotWithBgOffset,
        plotHist=params.plotHist,
        check_bg=params.check_bg,
        saturationImage=params.saturationImage,
    )
    return ReadnoiseResult(
        offset=float(offset),
        gain=float(gain),
        readnoise=float(readnoise),
        mean_electrons_per_exposure=float(mean_el),
        validmap=validmap,
        figures=figures,
        doc=doc,
    )
