"""Dataset Downloader dock widget."""

from __future__ import annotations

import os

from qtpy.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..download.manager import DownloadManager
from ..settings import Settings
from ..sources import resolve_source
from ..sources.base import ProgressEvent
from ._load import open_path


class DownloaderWidget(QWidget):
    """Download a dataset (local path / URL / record id) with progress + controls."""

    def __init__(self, napari_viewer=None, source: str = "") -> None:
        super().__init__()
        self.viewer = napari_viewer
        self.settings = Settings()
        self.manager = DownloadManager()
        self._last_path = None

        layout = QVBoxLayout(self)

        # -- source ---------------------------------------------------------
        layout.addWidget(QLabel("<b>Source</b> (local path, http(s) URL, or record id)"))
        self.source_edit = QLineEdit(source)
        self.source_edit.setPlaceholderText("e.g. 13457227.zarr  or  http://host:8001/.../download/exp.ome.zarr")
        layout.addWidget(self.source_edit)

        # -- storage dir ----------------------------------------------------
        layout.addWidget(QLabel("<b>Storage folder</b>"))
        store_row = QHBoxLayout()
        self.storage_edit = QLineEdit(self.settings.get("storage_dir"))
        self.storage_edit.setReadOnly(True)
        store_row.addWidget(self.storage_edit)
        self.change_btn = QPushButton("Change…")
        self.change_btn.clicked.connect(self._on_change_dir)
        store_row.addWidget(self.change_btn)
        layout.addLayout(store_row)

        # -- progress -------------------------------------------------------
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("Idle.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        # -- controls -------------------------------------------------------
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        self.restart_btn = QPushButton("Restart")
        self.restart_btn.clicked.connect(self._on_restart)
        for b in (self.start_btn, self.stop_btn, self.restart_btn):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        # -- options --------------------------------------------------------
        self.load_check = QCheckBox("Load into napari as a stack/layer when done")
        self.load_check.setChecked(bool(self.settings.get("load_as_stack")))
        layout.addWidget(self.load_check)

        self.to_processor_btn = QPushButton("Send to Processor →")
        self.to_processor_btn.setEnabled(False)
        self.to_processor_btn.clicked.connect(self._on_send_to_processor)
        layout.addWidget(self.to_processor_btn)

        layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    # -- storage dir --------------------------------------------------------
    def _on_change_dir(self) -> None:
        start = self.storage_edit.text() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Choose storage folder", start)
        if chosen:
            self.storage_edit.setText(chosen)
            self.settings.set("storage_dir", chosen)

    # -- download lifecycle -------------------------------------------------
    def _on_start(self) -> None:
        raw = self.source_edit.text().strip()
        if not raw:
            self.status.setText("Please enter a source.")
            return
        dest = self.storage_edit.text().strip() or self.settings.get("storage_dir")
        try:
            source = resolve_source(raw, self.settings)
        except Exception as exc:
            self.status.setText(f"<span style='color:#c0392b'>{exc}</span>")
            return

        self.settings.set("load_as_stack", self.load_check.isChecked())
        self._set_running(True)
        self.status.setText(f"Downloading from {source.name} …")
        self.progress.setValue(0)
        self.manager.start(
            source, dest,
            on_progress=self._on_progress,
            on_returned=self._on_returned,
            on_errored=self._on_errored,
            on_finished=self._on_finished,
        )

    def _on_stop(self) -> None:
        self.manager.stop()
        self.status.setText("Stopped.")
        self._set_running(False)

    def _on_restart(self) -> None:
        self._on_stop()
        self._on_start()

    # -- worker signal handlers (delivered on the GUI thread) ---------------
    def _on_progress(self, evt: ProgressEvent) -> None:
        frac = evt.fraction
        if frac is None:
            self.progress.setRange(0, 0)  # busy indicator
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(frac * 100))
        if evt.message:
            mb = ""
            if evt.total:
                mb = f"  ({evt.done / 1e6:.1f} / {evt.total / 1e6:.1f} MB)"
            self.status.setText(f"{evt.message}{mb}")

    def _on_returned(self, path: str) -> None:
        self._last_path = path
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status.setText(f"Done → {path}")
        self.to_processor_btn.setEnabled(bool(path))
        if self.load_check.isChecked() and self.viewer is not None and path:
            layers = open_path(self.viewer, path, as_stack=True)
            if layers:
                self.status.setText(f"Done → loaded {len(layers)} layer(s) from {os.path.basename(path)}")

    def _on_errored(self, exc: Exception) -> None:
        self.status.setText(f"<span style='color:#c0392b'>Error: {exc}</span>")

    def _on_finished(self) -> None:
        self._set_running(False)

    # -- handoff ------------------------------------------------------------
    def _on_send_to_processor(self) -> None:
        from .processor import ProcessorWidget

        path = self._last_path
        if not path:
            return
        proc = ProcessorWidget(self.viewer, input_dir=path)
        if self.viewer is not None:
            self.viewer.window.add_dock_widget(proc, name="Dataset Processor", area="right")
        else:  # standalone fallback
            proc.show()
            self._proc_ref = proc  # keep alive

    # -- helpers ------------------------------------------------------------
    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
