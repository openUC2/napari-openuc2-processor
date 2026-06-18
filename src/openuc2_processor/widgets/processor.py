"""Dataset Processor dock widget — a GUI over the tile-conversion engine."""

from __future__ import annotations

import os
from typing import Dict, List

from qtpy.QtCore import QObject, Signal
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..processing import PROCESSORS, ProcessParams, run_processors
from ..processing.registry import PROCESSOR_ORDER
from ._load import is_viewable, open_path


class _ProgressBridge(QObject):
    """Marshals progress from the worker thread to the GUI thread."""
    progress = Signal(str, int, int)


class ProcessorWidget(QWidget):
    """Pick an input folder, select processing modes, run, optionally visualize."""

    def __init__(self, napari_viewer=None, input_dir: str = "") -> None:
        super().__init__()
        self.viewer = napari_viewer
        self._worker = None
        self._bridge = _ProgressBridge()
        self._bridge.progress.connect(self._on_progress)
        self._mode_checks: Dict[str, QCheckBox] = {}

        # Scroll wrapper so the Run button stays reachable in a narrow dock.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)

        # -- input / output -------------------------------------------------
        layout.addWidget(QLabel("<b>Input folder</b> (tiles dir, session dir, or parent)"))
        in_row = QHBoxLayout()
        self.input_edit = QLineEdit(input_dir)
        in_row.addWidget(self.input_edit)
        in_btn = QPushButton("Browse…")
        in_btn.clicked.connect(self._browse_input)
        in_row.addWidget(in_btn)
        layout.addLayout(in_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output:"))
        self.output_edit = QLineEdit("")
        self.output_edit.setPlaceholderText("default: <input>/converted")
        out_row.addWidget(self.output_edit)
        out_btn = QPushButton("Browse…")
        out_btn.clicked.connect(self._browse_output)
        out_row.addWidget(out_btn)
        layout.addLayout(out_row)

        # -- modes (generated from the registry) ----------------------------
        modes_box = QGroupBox("Processing modes")
        modes_layout = QVBoxLayout(modes_box)
        for key in PROCESSOR_ORDER:
            proc = PROCESSORS[key]
            cb = QCheckBox(proc.label)
            cb.setToolTip(proc.description)
            if key == "composite":
                cb.setChecked(True)  # a sensible default
            cb.toggled.connect(self._update_advanced_enabled)
            self._mode_checks[key] = cb
            modes_layout.addWidget(cb)
        layout.addWidget(modes_box)

        # -- frame preprocessing (all modes) --------------------------------
        prep_box = QGroupBox("Frame preprocessing (applied to every tile)")
        prep = QFormLayout(prep_box)
        flip_row = QHBoxLayout()
        self.flip_x_check = QCheckBox("Flip X")
        self.flip_y_check = QCheckBox("Flip Y")
        flip_row.addWidget(self.flip_x_check)
        flip_row.addWidget(self.flip_y_check)
        flip_row.addStretch(1)
        flip_w = QWidget()
        flip_w.setLayout(flip_row)
        prep.addRow("Flip", flip_w)
        self.rotate_combo = QComboBox()
        for deg in (0, 90, 180, 270):
            self.rotate_combo.addItem(f"{deg}°", deg)
        prep.addRow("Rotate (CCW)", self.rotate_combo)
        layout.addWidget(prep_box)

        # -- advanced / ashlar params --------------------------------------
        self.adv_box = QGroupBox("Advanced (ashlar + discovery)")
        adv = QFormLayout(self.adv_box)
        self.pixel_spin = QDoubleSpinBox()
        self.pixel_spin.setDecimals(4)
        self.pixel_spin.setRange(0.0001, 1000.0)
        self.pixel_spin.setValue(1.0)
        self.pixel_spin.setSuffix(" µm/px")
        adv.addRow("Pixel size", self.pixel_spin)
        self.shift_spin = QDoubleSpinBox()
        self.shift_spin.setRange(0.0, 100000.0)
        self.shift_spin.setValue(50.0)
        self.shift_spin.setSuffix(" µm")
        adv.addRow("Max shift", self.shift_spin)
        self.align_spin = QSpinBox()
        self.align_spin.setRange(0, 64)
        adv.addRow("Align channel", self.align_spin)
        proto_row = QHBoxLayout()
        self.proto_edit = QLineEdit("")
        self.proto_edit.setPlaceholderText("auto-detect")
        proto_row.addWidget(self.proto_edit)
        proto_btn = QPushButton("…")
        proto_btn.clicked.connect(self._browse_protocol)
        proto_row.addWidget(proto_btn)
        proto_w = QWidget()
        proto_w.setLayout(proto_row)
        adv.addRow("Protocol JSON", proto_w)
        layout.addWidget(self.adv_box)

        # -- run ------------------------------------------------------------
        self.visualize_check = QCheckBox("Open results in napari when finished")
        layout.addWidget(self.visualize_check)

        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self._on_run)
        layout.addWidget(self.run_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.status = QLabel("Idle.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        layout.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self._update_advanced_enabled()

    # -- pickers ------------------------------------------------------------
    def _browse_input(self) -> None:
        start = self.input_edit.text() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Choose input folder", start)
        if chosen:
            self.input_edit.setText(chosen)

    def _browse_output(self) -> None:
        start = self.output_edit.text() or self.input_edit.text() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if chosen:
            self.output_edit.setText(chosen)

    def _browse_protocol(self) -> None:
        start = self.input_edit.text() or os.path.expanduser("~")
        chosen, _ = QFileDialog.getOpenFileName(self, "Protocol JSON", start, "JSON (*.json)")
        if chosen:
            self.proto_edit.setText(chosen)

    # -- run lifecycle ------------------------------------------------------
    def _selected_keys(self) -> List[str]:
        return [k for k, cb in self._mode_checks.items() if cb.isChecked()]

    def _update_advanced_enabled(self) -> None:
        any_ashlar = any(
            PROCESSORS[k].needs_ashlar_params for k in self._selected_keys()
        )
        self.adv_box.setEnabled(True)
        self.pixel_spin.setEnabled(any_ashlar)
        self.shift_spin.setEnabled(any_ashlar)
        self.align_spin.setEnabled(any_ashlar)

    def _on_run(self) -> None:
        input_dir = self.input_edit.text().strip()
        if not input_dir or not os.path.isdir(input_dir):
            self.status.setText("Please choose a valid input folder.")
            return
        keys = self._selected_keys()
        if not keys:
            self.status.setText("Select at least one processing mode.")
            return

        params = ProcessParams(
            output_dir=self.output_edit.text().strip() or None,
            protocol_json=self.proto_edit.text().strip() or None,
            pixel_size=self.pixel_spin.value(),
            maximum_shift=self.shift_spin.value(),
            align_channel=self.align_spin.value(),
            flip_x=self.flip_x_check.isChecked(),
            flip_y=self.flip_y_check.isChecked(),
            rotate=int(self.rotate_combo.currentData()),
        )

        from napari.qt.threading import thread_worker

        self.run_btn.setEnabled(False)
        self.progress.setRange(0, 0)  # busy until first tick
        self.status.setText("Discovering tiles…")

        bridge = self._bridge

        @thread_worker
        def _job():
            return run_processors(
                input_dir, keys, params,
                progress_cb=lambda label, d, t: bridge.progress.emit(label, d, t),
            )

        worker = _job()
        worker.returned.connect(self._on_done)
        worker.errored.connect(self._on_error)
        worker.finished.connect(lambda: self.run_btn.setEnabled(True))
        self._worker = worker
        worker.start()

    # -- worker signals -----------------------------------------------------
    def _on_progress(self, label: str, done: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        if label and label != "done":
            self.status.setText(f"Running: {label}  ({done + 1}/{total})")

    def _on_done(self, results: Dict[str, List[str]]) -> None:
        all_paths = [p for paths in results.values() for p in paths]
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        n = len(all_paths)
        if self.visualize_check.isChecked() and self.viewer is not None:
            opened = 0
            for p in all_paths:
                if is_viewable(p):
                    if open_path(self.viewer, p):
                        opened += 1
            self.status.setText(f"Done: wrote {n} file(s); opened {opened} in napari.")
        else:
            out = self.output_edit.text().strip() or os.path.join(
                self.input_edit.text().strip(), "converted"
            )
            self.status.setText(f"Done: wrote {n} file(s) to {out}")

    def _on_error(self, exc: Exception) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status.setText(f"<span style='color:#c0392b'>Error: {exc}</span>")
