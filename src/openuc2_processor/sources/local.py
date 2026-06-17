"""Local-path source — nothing to download, the data already exists on disk."""

from __future__ import annotations

import os
from typing import Iterator

from .base import ProgressEvent, Source


class LocalSource(Source):
    """Pass-through for a source that is already a local file or directory."""

    @property
    def name(self) -> str:
        return f"Local: {os.path.basename(self.raw.rstrip('/')) or self.raw}"

    def iter_download(self, dest_dir: str) -> Iterator[ProgressEvent]:
        # No transfer needed; report a single completed tick.
        yield ProgressEvent(1, 1, "Using local data")
        return self.raw
