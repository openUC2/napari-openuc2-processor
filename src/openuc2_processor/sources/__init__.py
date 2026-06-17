"""Pluggable download-source resolver.

``resolve_source`` maps a raw string to a concrete :class:`Source`:

- an existing local path        -> :class:`LocalSource`
- an ``http(s)://`` URL          -> :class:`HttpUrlSource`
- a bare numeric id (``13457227``) -> :class:`ZenodoSource` (base from settings)

Register a new source type by adding a branch here.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from .base import ProgressEvent, Source
from .http_url import HttpUrlSource
from .local import LocalSource
from .zenodo import ZenodoSource

__all__ = [
    "ProgressEvent",
    "Source",
    "LocalSource",
    "HttpUrlSource",
    "ZenodoSource",
    "resolve_source",
]

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_ID_RE = re.compile(r"^(\d+)(?:\.[\w.]+)?$")  # 13457227 or 13457227.zarr


def resolve_source(source: str, settings=None) -> Source:
    """Resolve a raw source string into a concrete :class:`Source`."""
    s = (source or "").strip().strip('"').strip("'")
    if not s:
        raise ValueError("Empty source.")

    if os.path.exists(s):
        return LocalSource(s)

    if _URL_RE.match(s):
        return HttpUrlSource(s)

    m = _ID_RE.match(s)
    if m:
        base = "https://zenodo.org"
        if settings is not None:
            base = settings.get("id_base_url", base) or base
        return ZenodoSource(m.group(1), base_url=base)

    # Scheme-less host/path (e.g. "example.org/data/x.zip") -> assume https.
    if "/" in s and "." in s:
        return HttpUrlSource("https://" + s)

    raise ValueError(
        f"Could not resolve source {source!r}. Expected a local path, an "
        "http(s) URL, or a numeric record id."
    )
