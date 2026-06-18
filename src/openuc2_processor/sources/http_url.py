"""HTTP(S) download source + shared streaming/zip helpers."""

from __future__ import annotations

import os
import re
import zipfile
from typing import Iterator, Optional
from urllib.parse import unquote, urlparse

from .base import ProgressEvent, Source

DEFAULT_CHUNK = 1 << 20  # 1 MiB

# Local zip-file magic numbers (regular, empty-archive, spanned).
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def _filename_from(url: str, content_disposition: Optional[str]) -> str:
    """Best-effort output filename from Content-Disposition or the URL path."""
    if content_disposition:
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition)
        if m:
            return unquote(m.group(1).strip())
    path = urlparse(url).path
    name = os.path.basename(path.rstrip("/")) or "download"
    return unquote(name)


def _looks_like_zip(path: str) -> bool:
    """Detect a zip by its magic bytes, regardless of file extension."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) in _ZIP_MAGIC
    except OSError:
        return False


def _iter_write(
    resp, dest_path: str, *, chunk: int, done_base: int, total: int, label: str
) -> Iterator[ProgressEvent]:
    """Write a streaming response to disk, yielding progress; returns cumulative bytes."""
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    done = done_base
    with open(dest_path, "wb") as fh:
        for block in resp.iter_content(chunk_size=chunk):
            if not block:
                continue
            fh.write(block)
            done += len(block)
            yield ProgressEvent(done, total, label)
    return done


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
    single aggregate progress bar. Returns the cumulative byte count.
    """
    import requests

    sess = session or requests
    with sess.get(url, stream=True, timeout=60, allow_redirects=True) as resp:
        resp.raise_for_status()
        clen = resp.headers.get("Content-Length")
        ttl = total or ((int(clen) + done_base) if clen and clen.isdigit() else 0)
        done = yield from _iter_write(
            resp, dest_path, chunk=chunk, done_base=done_base, total=ttl,
            label=label or os.path.basename(dest_path),
        )
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
    """Download a single file (or a folder-zip) from an http(s) URL.

    ImSwitch's ``/FileManager/download/<folder>`` endpoint streams a zip whose
    name/extension may not survive the transfer, so we detect zips by
    Content-Type *and* by magic bytes and always extract them, returning the
    extracted folder as the base path.
    """

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url

    @property
    def name(self) -> str:
        return f"URL: {os.path.basename(urlparse(self.url).path) or self.url}"

    def iter_download(self, dest_dir: str) -> Iterator[ProgressEvent]:
        import requests

        os.makedirs(dest_dir, exist_ok=True)
        with requests.get(self.url, stream=True, timeout=60, allow_redirects=True) as resp:
            resp.raise_for_status()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            fname = _filename_from(self.url, resp.headers.get("Content-Disposition"))
            clen = resp.headers.get("Content-Length")
            ttl = int(clen) if clen and clen.isdigit() else 0
            dest_path = os.path.join(dest_dir, fname)
            yield from _iter_write(
                resp, dest_path, chunk=DEFAULT_CHUNK, done_base=0, total=ttl, label=fname
            )

        is_zip = (
            dest_path.lower().endswith(".zip")
            or "zip" in ctype
            or _looks_like_zip(dest_path)
        )
        if is_zip:
            yield ProgressEvent(1, 1, f"Extracting {fname}…")
            return extract_zip(dest_path, dest_dir)
        return dest_path
