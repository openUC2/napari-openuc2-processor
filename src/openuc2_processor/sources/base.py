"""Abstract download source + progress event."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class ProgressEvent:
    """A single progress tick emitted during a download."""
    done: int                 # bytes (or items) completed so far
    total: int                # total bytes (0 == indeterminate)
    message: str = ""

    @property
    def fraction(self) -> Optional[float]:
        """0..1 progress, or None when the total is unknown."""
        return (self.done / self.total) if self.total else None


class Source(ABC):
    """A resolvable data source.

    ``iter_download`` is a generator: it *yields* :class:`ProgressEvent` ticks and
    *returns* (PEP 380) the final local path on disk. Implementations must yield
    frequently enough (e.g. per network chunk) that a consumer can abort between
    yields.
    """

    def __init__(self, raw: str) -> None:
        self.raw = raw

    @property
    @abstractmethod
    def name(self) -> str:
        """Short human-readable label for the GUI."""

    @abstractmethod
    def iter_download(self, dest_dir: str) -> Iterator[ProgressEvent]:
        """Download into *dest_dir*; yield progress; return the final local path."""
        raise NotImplementedError
