"""HTTP(S) download source + shared streaming/zip helpers."""

from __future__ import annotations

import os
import re
import zipfile
from typing import Iterator, Optional
from urllib.parse import unquote, urlparse

from .base import ProgressEvent, Source

DEFAULT_CHUNK = 1 << 20  # 1 MiB


def _filename_from(url: str, content_disposition: Optional[str]) -> str:
    """Best-effort output filename from Content-Disposition or the URL path."""
    if content_disposition:
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition)
        if m:
            return unquote(m.group(1).strip())
    path = urlparse(url).path
    name = os.path.basename(path.rstrip("/")) or "download"
    return unquote(name)


def stream_download(
    url: str,
    dest_path: str,
    *,
    session=None,
    chunk: int = DEFAULT_CHUNK,
    done_base: int = 0,
    total: int = 0,
    label: str = "",
) -> Iterator[ProgressEvent]:
    """Stream *url* to *dest_path*, yielding progress.

    ``done_base``/``total`` let callers (e.g. multi-file Zenodo records) present a
    single aggregate progress bar. Returns the cumulative byte count
    (``done_base`` + size of this file) via the generator's return value.
    """
    import requests

    sess = session or requests
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with sess.get(url, stream=True, timeout=60, allow_redirects=True) as resp:
        resp.raise_for_status()
        clen = resp.headers.get("Content-Length")
        ttl = total or ((int(clen) + done_base) if clen and clen.isdigit() else 0)
        done = done_base
        lbl = label or os.path.basename(dest_path)
        with open(dest_path, "wb") as fh:
            for block in resp.iter_content(chunk_size=chunk):
                if not block:
                    continue
                fh.write(block)
                done += len(block)
                yield ProgressEvent(done, ttl, lbl)
    return done


def extract_zip(zip_path: str, dest_dir: str, remove: bool = True) -> str:
    """Extract a zip into *dest_dir*; return the top-level extracted path."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        zf.extractall(dest_dir)
    if remove:
        try:
            os.remove(zip_path)
        except OSError:
            pass
    tops = {n.split("/", 1)[0] for n in names if n}
    if len(tops) == 1:
        return os.path.join(dest_dir, tops.pop())
    return dest_dir


class HttpUrlSource(Source):
    """Download a single file (or ImSwitch folder-zip) from an http(s) URL."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url

    @property
    def name(self) -> str:
        return f"URL: {os.path.basename(urlparse(self.url).path) or self.url}"

    def iter_download(self, dest_dir: str) -> Iterator[ProgressEvent]:
        import requests

        os.makedirs(dest_dir, exist_ok=True)
        # A HEAD avoids guessing the filename wrong; fall back to the URL path.
        fname = _filename_from(urlparse(self.url).path, None)
        try:
            head = requests.head(self.url, allow_redirects=True, timeout=30)
            fname = _filename_from(self.url, head.headers.get("Content-Disposition")) or fname
        except Exception:
            pass

        dest_path = os.path.join(dest_dir, fname)
        yield from stream_download(self.url, dest_path, label=fname)

        if dest_path.lower().endswith(".zip"):
            yield ProgressEvent(1, 1, f"Extracting {fname}…")
            return extract_zip(dest_path, dest_dir)
        return dest_path
