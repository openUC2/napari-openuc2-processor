"""Zenodo record source — resolve a bare numeric ID to its files and download them."""

from __future__ import annotations

import os
from typing import Iterator

from .base import ProgressEvent, Source
from .http_url import extract_zip, stream_download


class ZenodoSource(Source):
    """Resolve a Zenodo record id (e.g. ``13457227``) and download its files."""

    def __init__(self, record_id: str, base_url: str = "https://zenodo.org") -> None:
        super().__init__(str(record_id))
        self.record_id = str(record_id)
        self.base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return f"Zenodo record {self.record_id}"

    @property
    def api_url(self) -> str:
        return f"{self.base_url}/api/records/{self.record_id}"

    @staticmethod
    def _file_url(entry: dict) -> str:
        links = entry.get("links", {}) or {}
        # Newer API: links.content; legacy: links.download / links.self
        return links.get("content") or links.get("download") or links.get("self")

    def iter_download(self, dest_dir: str) -> Iterator[ProgressEvent]:
        import requests

        resp = requests.get(self.api_url, timeout=30)
        resp.raise_for_status()
        meta = resp.json()
        files = meta.get("files", []) or []
        if not files:
            raise RuntimeError(f"Zenodo record {self.record_id} has no files.")

        rec_dir = os.path.join(dest_dir, self.record_id)
        os.makedirs(rec_dir, exist_ok=True)

        total = sum(int(f.get("size", 0) or 0) for f in files)
        done_base = 0
        written = []
        for entry in files:
            key = entry.get("key") or entry.get("filename") or "file"
            url = self._file_url(entry)
            if not url:
                continue
            dest = os.path.join(rec_dir, key)
            done_base = yield from stream_download(
                url, dest, done_base=done_base, total=total, label=key
            )
            written.append(dest)

        if not written:
            raise RuntimeError(f"Zenodo record {self.record_id}: no downloadable file links.")

        # Single zip -> extract; single file -> return it; otherwise the record dir.
        if len(written) == 1 and written[0].lower().endswith(".zip"):
            yield ProgressEvent(total or 1, total or 1, "Extracting…")
            return extract_zip(written[0], rec_dir)
        if len(written) == 1:
            return written[0]
        return rec_dir
