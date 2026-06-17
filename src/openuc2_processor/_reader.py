"""napari reader contribution.

Enables ``napari --plugin openuc2-processor <source>``. Rather than silently
reading layers, the reader opens the **Dataset Downloader** docked widget
pre-filled with ``<source>`` (so the user gets progress / stop / restart /
storage-folder / load-as-stack controls), and returns the ``[(None,)]``
"no layers added" sentinel.
"""

from __future__ import annotations

import os
import re

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_ID_RE = re.compile(r"^\d+(?:\.[\w.]+)?$")


def _is_handled(path) -> bool:
    """True for sources this plugin knows how to resolve."""
    if not isinstance(path, str):
        return False
    s = path.strip().strip('"').strip("'")
    if not s:
        return False
    if os.path.exists(s):
        return True
    if _URL_RE.match(s):
        return True
    if _ID_RE.match(s):
        return True
    if "/" in s and "." in s:  # scheme-less host/path
        return True
    return False


def napari_get_reader(path):
    """Return our reader if we can handle *path*, else None."""
    candidate = path[0] if isinstance(path, (list, tuple)) and path else path
    if not _is_handled(candidate):
        return None
    return reader_function


def reader_function(path):
    """Open the Downloader widget pre-filled with the source. Adds no layers."""
    source = path[0] if isinstance(path, (list, tuple)) and path else path

    viewer = None
    try:
        import napari

        viewer = napari.current_viewer()
    except Exception:
        viewer = None

    if viewer is not None:
        try:
            from .widgets.downloader import DownloaderWidget

            widget = DownloaderWidget(viewer, source=str(source))
            viewer.window.add_dock_widget(
                widget, name="Dataset Downloader", area="right"
            )
        except Exception as exc:  # pragma: no cover - GUI dependent
            print(f"[openuc2-processor] could not open downloader: {exc}")

    # Signal a successful read that contributes no layers.
    return [(None,)]
