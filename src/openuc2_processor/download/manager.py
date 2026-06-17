"""DownloadManager — runs a :class:`Source` download off the GUI thread.

Wraps napari's ``thread_worker`` around the source's generator so the widget can
show progress and Stop / Restart without blocking the event loop. A synchronous
helper (:func:`run_sync`) is provided for tests / headless use.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..sources.base import ProgressEvent, Source


def run_sync(
    source: Source,
    dest_dir: str,
    on_progress: Optional[Callable[[ProgressEvent], None]] = None,
) -> str:
    """Run a download synchronously (no Qt). Returns the final local path."""
    gen = source.iter_download(dest_dir)
    result = dest_dir
    try:
        while True:
            evt = next(gen)
            if on_progress is not None:
                on_progress(evt)
    except StopIteration as stop:
        if stop.value:
            result = stop.value
    return result


class DownloadManager:
    """Manage a single in-flight download with start / stop / restart."""

    def __init__(self) -> None:
        self._worker = None
        self._running = False
        self._last_args: Optional[tuple] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(
        self,
        source: Source,
        dest_dir: str,
        *,
        on_progress: Optional[Callable[[ProgressEvent], None]] = None,
        on_returned: Optional[Callable[[str], None]] = None,
        on_errored: Optional[Callable[[Exception], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ):
        """Launch the download in a worker thread. Returns the worker."""
        from napari.qt.threading import thread_worker

        self._last_args = (
            source, dest_dir,
            dict(on_progress=on_progress, on_returned=on_returned,
                 on_errored=on_errored, on_finished=on_finished),
        )

        @thread_worker
        def _job():
            # `yield from` re-emits the source's ProgressEvents and captures the
            # returned local path as this worker's return value.
            path = yield from source.iter_download(dest_dir)
            return path

        worker = _job()
        if on_progress is not None:
            worker.yielded.connect(on_progress)
        if on_returned is not None:
            worker.returned.connect(on_returned)
        if on_errored is not None:
            worker.errored.connect(on_errored)

        def _on_finished():
            self._running = False
            if on_finished is not None:
                on_finished()

        worker.finished.connect(_on_finished)
        self._worker = worker
        self._running = True
        worker.start()
        return worker

    def stop(self) -> None:
        """Request the running worker to abort at its next yield."""
        if self._worker is not None and self._running:
            try:
                self._worker.quit()
            except Exception:
                pass
        self._running = False

    def restart(self):
        """Stop any current download and start a fresh one with the same args."""
        if self._last_args is None:
            return None
        self.stop()
        source, dest_dir, kw = self._last_args
        return self.start(source, dest_dir, **kw)
