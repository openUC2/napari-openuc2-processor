"""Helpers for loading downloaded / processed paths into a napari viewer."""

from __future__ import annotations

import glob
import os
import re
from typing import List

_IMAGE_EXTS = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp")
_DIGITS_RE = re.compile(r"(\d+)")


def is_viewable(path: str) -> bool:
    """True for files/dirs napari can reasonably display."""
    p = path.lower()
    if p.endswith(".zarr") or p.endswith(".ome.zarr"):
        return True
    return p.endswith(_IMAGE_EXTS)


def _natural_key(path: str):
    """Sort key ordering embedded numbers numerically (timepoint 2 before
    10) instead of lexicographically, as produced by e.g. '..._experiment0_2_...'
    vs '..._experiment0_10_...' directory names."""
    return [int(tok) if tok.isdigit() else tok.lower() for tok in _DIGITS_RE.split(path)]


def open_path(viewer, path: str, as_stack: bool = False) -> List:
    """Open *path* in *viewer*. Returns the created layers (possibly empty).

    - ``.zarr`` / ``.ome.zarr`` dirs are handed to napari (napari-ome-zarr).
    - a directory of images is opened as separate layers, or as one stack when
      ``as_stack`` is set.
    - a single image file is opened directly.
    """
    if viewer is None or not path or not os.path.exists(path):
        return []
    try:
        if os.path.isdir(path):
            low = path.lower()
            if low.endswith(".zarr") or low.endswith(".ome.zarr"):
                return viewer.open(path)
            by_ext: dict[str, list[str]] = {}
            for ext in _IMAGE_EXTS:
                found = glob.glob(os.path.join(path, f"*{ext}"))
                found += glob.glob(os.path.join(path, "**", f"*{ext}"), recursive=True)
                if found:
                    by_ext[ext] = sorted(set(found), key=_natural_key)
            if not by_ext:
                return viewer.open(path)
            if as_stack:
                # napari's stack loader requires one consistent extension;
                # use the largest group (the actual timepoint series) and
                # skip incidental images of other types (e.g. report plots).
                imgs = max(by_ext.values(), key=len)
                return viewer.open(imgs, stack=True)
            imgs = sorted({p for group in by_ext.values() for p in group}, key=_natural_key)
            return viewer.open(imgs, stack=False)
        return viewer.open(path)
    except Exception as exc:  # pragma: no cover - viewer-dependent
        print(f"[openuc2-processor] could not open {path}: {exc}")
        return []
