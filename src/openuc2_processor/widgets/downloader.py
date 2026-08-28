"""Dataset Downloader dock widget."""

from __future__ import annotations

import os
import re

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..download.manager import DownloadManager
from ..settings import Settings
from ..sources import microscope, resolve_source
from ..sources.base import ProgressEvent
from ._load import open_path

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_ID_RE = re.compile(r"^\d+(?:\.[\w.]+)?$")


class DownloaderWidget(QWidget):
    """Download a dataset (URL / local path / record id) with progress + controls."""

    def __init__(self, napari_viewer=None, source: str = "") -> None:
        super().__init__()
        self.viewer = napari_viewer
        self.settings = Settings()
        self.manager = DownloadManager()
        self._last_path = None
        self._micro_host = ""
        self._micro_path = ""
        self._micro_selected = None

        # Scroll wrapper so controls stay reachable in a narrow dock.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)

        # -- source (three tabs) -------------------------------------------
        layout.addWidget(QLabel("<b>Source</b>"))
        self.tabs = QTabWidget()

        url_tab = QWidget()
        url_l = QVBoxLayout(url_tab)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("http(s)://host/imswitch/api/FileManager/download/…")
        url_l.addWidget(self.url_edit)
        self.tabs.addTab(url_tab, "URL")

        local_tab = QWidget()
        local_l = QVBoxLayout(local_tab)
        self.local_edit = QLineEdit()
        self.local_edit.setPlaceholderText("/path/to/folder or file")
        local_l.addWidget(self.local_edit)
        local_btns = QHBoxLayout()
        b_folder = QPushButton("Browse folder…")
        b_folder.clicked.connect(self._browse_local_folder)
        b_file = QPushButton("Browse file…")
        b_file.clicked.connect(self._browse_local_file)
        local_btns.addWidget(b_folder)
        local_btns.addWidget(b_file)
        local_l.addLayout(local_btns)
        local_l.addWidget(QLabel("<i>Local data is used in place — not downloaded.</i>"))
        self.tabs.addTab(local_tab, "Local path")

        zen_tab = QWidget()
        zen_l = QVBoxLayout(zen_tab)
        self.zen_edit = QLineEdit()
        self.zen_edit.setPlaceholderText("Zenodo record id, e.g. 13457227")
        zen_l.addWidget(self.zen_edit)
        self.tabs.addTab(zen_tab, "Zenodo ID")

        micro_tab = QWidget()
        micro_l = QVBoxLayout(micro_tab)
        self.micro_host_edit = QLineEdit(self.settings.get("last_microscope_url"))
        self.micro_host_edit.setPlaceholderText("192.168.1.100:8001 or http://host:port")
        micro_l.addWidget(self.micro_host_edit)
        self.micro_connect_btn = QPushButton("Connect")
        self.micro_connect_btn.clicked.connect(self._micro_connect)
        micro_l.addWidget(self.micro_connect_btn)

        micro_nav = QHBoxLayout()
        self.micro_up_btn = QPushButton("↑ Up")
        self.micro_up_btn.setEnabled(False)
        self.micro_up_btn.clicked.connect(self._micro_up)
        micro_nav.addWidget(self.micro_up_btn)
        self.micro_breadcrumb = QLabel("Not connected.")
        self.micro_breadcrumb.setWordWrap(True)
        micro_nav.addWidget(self.micro_breadcrumb, 1)
        micro_l.addLayout(micro_nav)

        self.micro_list = QListWidget()
        self.micro_list.itemClicked.connect(self._micro_item_clicked)
        self.micro_list.itemDoubleClicked.connect(self._micro_item_double_clicked)
        micro_l.addWidget(self.micro_list)

        self.micro_selected_label = QLabel("No dataset selected.")
        self.micro_selected_label.setWordWrap(True)
        micro_l.addWidget(self.micro_selected_label)
        micro_l.addWidget(QLabel(
            "<i>Double-click a folder to open it, click a file/folder to select it "
            "for download.</i>"
        ))
        self.tabs.addTab(micro_tab, "Microscope")

        layout.addWidget(self.tabs)

        # -- storage dir ----------------------------------------------------
        layout.addWidget(QLabel("<b>Storage folder</b> (for downloads)"))
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
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        if source:
            self._prefill(source)

    # -- source helpers -----------------------------------------------------
    def _prefill(self, source: str) -> None:
        s = source.strip().strip('"').strip("'")
        if _URL_RE.match(s):
            self.url_edit.setText(s)
            self.tabs.setCurrentIndex(0)
        elif os.path.exists(s):
            self.local_edit.setText(s)
            self.tabs.setCurrentIndex(1)
        elif _ID_RE.match(s):
            self.zen_edit.setText(s)
            self.tabs.setCurrentIndex(2)
        else:
            self.url_edit.setText(s)
            self.tabs.setCurrentIndex(0)

    def _current_source(self) -> str:
        idx = self.tabs.currentIndex()
        if idx == 0:
            return self.url_edit.text().strip()
        if idx == 1:
            return self.local_edit.text().strip()
        if idx == 2:
            return self.zen_edit.text().strip()
        # Microscope tab: resolve the item picked in the browser below.
        if not self._micro_host or not self._micro_selected:
            return ""
        try:
            return microscope.download_url(self._micro_host, self._micro_selected)
        except Exception:
            return ""

    def _browse_local_folder(self) -> None:
        start = self.local_edit.text() or self.settings.get("storage_dir")
        chosen = QFileDialog.getExistingDirectory(self, "Choose data folder", start)
        if chosen:
            self.local_edit.setText(chosen)
            self.tabs.setCurrentIndex(1)

    def _browse_local_file(self) -> None:
        start = self.local_edit.text() or self.settings.get("storage_dir")
        chosen, _ = QFileDialog.getOpenFileName(self, "Choose data file", start)
        if chosen:
            self.local_edit.setText(chosen)
            self.tabs.setCurrentIndex(1)

    # -- microscope browser --------------------------------------------------
    def _micro_connect(self) -> None:
        raw = self.micro_host_edit.text().strip()
        if not raw:
            self.micro_breadcrumb.setText("Enter the microscope's host:port first.")
            return
        self._micro_host = raw
        self._micro_path = ""
        self._micro_selected = None
        self.micro_selected_label.setText("No dataset selected.")
        self.settings.set("last_microscope_url", raw)
        self._micro_refresh()

    def _micro_refresh(self) -> None:
        try:
            items = microscope.children(self._micro_host, self._micro_path)
        except Exception as exc:
            self.micro_breadcrumb.setText(f"<span style='color:#c0392b'>Could not list datasets: {exc}</span>")
            return
        self.micro_list.clear()
        items.sort(key=lambda it: (not it.get("isDirectory"), (it.get("name") or "").lower()))
        for it in items:
            icon = "\U0001F4C1" if it.get("isDirectory") else "\U0001F4C4"
            label = f"{icon} {it.get('name')}"
            size = it.get("size")
            if not it.get("isDirectory") and size is not None:
                label += f"  ({size / 1e6:.1f} MB)"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.UserRole, it)
            self.micro_list.addItem(list_item)
        self.micro_breadcrumb.setText(f"/{self._micro_path.strip('/')}" if self._micro_path else "/ (root)")
        self.micro_up_btn.setEnabled(bool(self._micro_path))

    def _micro_up(self) -> None:
        if not self._micro_path:
            return
        parent = self._micro_path.rsplit("/", 1)[0]
        self._micro_path = parent if parent not in ("", "/") else ""
        self._micro_selected = None
        self.micro_selected_label.setText("No dataset selected.")
        self._micro_refresh()

    def _micro_item_clicked(self, list_item: "QListWidgetItem") -> None:
        it = list_item.data(Qt.UserRole)
        self._micro_selected = it.get("path")
        kind = "folder" if it.get("isDirectory") else "file"
        self.micro_selected_label.setText(f"Selected {kind}: {it.get('name')}")

    def _micro_item_double_clicked(self, list_item: "QListWidgetItem") -> None:
        it = list_item.data(Qt.UserRole)
        if it.get("isDirectory"):
            self._micro_path = it.get("path") or ""
            self._micro_selected = None
            self.micro_selected_label.setText("No dataset selected.")
            self._micro_refresh()
        else:
            self._micro_item_clicked(list_item)

    # -- storage dir --------------------------------------------------------
    def _on_change_dir(self) -> None:
        start = self.storage_edit.text() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Choose storage folder", start)
        if chosen:
            self.storage_edit.setText(chosen)
            self.settings.set("storage_dir", chosen)

    # -- download lifecycle -------------------------------------------------
    def _on_start(self) -> None:
        raw = self._current_source()
        if not raw:
            if self.tabs.currentIndex() == 3:
                self.status.setText("Connect to a microscope and select a dataset first.")
            else:
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
        self.status.setText(f"Working: {source.name} …")
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
