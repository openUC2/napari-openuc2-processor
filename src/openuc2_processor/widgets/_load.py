"""Helpers for loading downloaded / processed paths into a napari viewer."""

from __future__ import annotations

import glob
import os
from typing import List

_IMAGE_EXTS = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp")


def is_viewable(path: str) -> bool:
    """True for files/dirs napari can reasonably display."""
    p = path.lower()
    if p.endswith(".zarr") or p.endswith(".ome.zarr"):
        return True
    return p.endswith(_IMAGE_EXTS)


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
            imgs = []
            for ext in _IMAGE_EXTS:
                imgs.extend(glob.glob(os.path.join(path, f"*{ext}")))
                imgs.extend(glob.glob(os.path.join(path, "**", f"*{ext}"), recursive=True))
            imgs = sorted(set(imgs))
            if imgs:
                return viewer.open(imgs, stack=as_stack)
            return viewer.open(path)
        return viewer.open(path)
    except Exception as exc:  # pragma: no cover - viewer-dependent
        print(f"[openuc2-processor] could not open {path}: {exc}")
        return []
