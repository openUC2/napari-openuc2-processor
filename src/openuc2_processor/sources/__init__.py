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
_EMBEDDED_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _clean_source(source: str) -> str:
    """Tolerate common copy/paste mistakes.

    Strips surrounding quotes and, if a whole command line was pasted
    (e.g. ``napari --plugin openuc2-processor "http://host/..."``), extracts the
    embedded URL so the user doesn't get a confusing DNS error.
    """
    s = (source or "").strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        s = s[1:-1].strip()
    if not _URL_RE.match(s):
        m = _EMBEDDED_URL_RE.search(s)
        if m:
            return m.group(0).strip().strip('"').strip("'")
    return s


def resolve_source(source: str, settings=None) -> Source:
    """Resolve a raw source string into a concrete :class:`Source`."""
    s = _clean_source(source)
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
    # Reject anything with whitespace so a malformed paste fails clearly instead
    # of becoming a bogus hostname.
    if "/" in s and "." in s and not re.search(r"\s", s):
        return HttpUrlSource("https://" + s)

    raise ValueError(
        f"Could not resolve source {source!r}. Expected a local path, an "
        "http(s) URL, or a numeric record id."
    )
