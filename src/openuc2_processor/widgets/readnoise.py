"""Read-noise / photon-transfer calibration dock widget.

Wraps NanoImagingPack's ``cal_readnoise`` over two open image layers — a
foreground/bright series and a background/dark series captured under
matching camera settings — and displays the resulting photon-transfer-curve
and histogram plots inline.
"""

from __future__ import annotations

import os
from typing import List

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..processing.readnoise import ReadnoiseParams, run_cal_readnoise


class _OptionalRange(QWidget):
    """A checkbox-gated [min, max] pair; contributes ``None`` when unchecked."""

    def __init__(self, label: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox(label)
        self.lo = QDoubleSpinBox()
        self.hi = QDoubleSpinBox()
        for sb in (self.lo, self.hi):
            sb.setRange(-1e9, 1e9)
            sb.setDecimals(2)
            sb.setEnabled(False)
        self.enabled.toggled.connect(self.lo.setEnabled)
        self.enabled.toggled.connect(self.hi.setEnabled)
        row.addWidget(self.enabled)
        row.addWidget(self.lo)
        row.addWidget(QLabel("–"))
        row.addWidget(self.hi)

    def value(self):
        if not self.enabled.isChecked():
            return None
        return (self.lo.value(), self.hi.value())


class ReadnoiseWidget(QWidget):
    """Pick foreground/background stacks, tune cal_readnoise params, run, show plots."""

    def __init__(self, napari_viewer=None) -> None:
        super().__init__()
        self.viewer = napari_viewer
        self._plot_windows: List[QDialog] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)

        # -- stack selection --------------------------------------------------
        stacks_box = QGroupBox("Stacks")
        stacks = QFormLayout(stacks_box)
        self.fg_combo = QComboBox()
        self.bg_combo = QComboBox()
        stacks.addRow("Foreground (bright)", self.fg_combo)
        stacks.addRow("Background (dark)", self.bg_combo)
        refresh_btn = QPushButton("Refresh layer list")
        refresh_btn.clicked.connect(self._refresh_layers)
        stacks.addRow("", refresh_btn)
        layout.addWidget(stacks_box)

        # -- parameters ---------------------------------------------------------
        params_box = QGroupBox("Calibration parameters")
        p = QFormLayout(params_box)
        self.camera_edit = QLineEdit()
        self.camera_edit.setPlaceholderText("optional, used as plot title")
        p.addRow("Camera name", self.camera_edit)
        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(2, 100000)
        self.bins_spin.setValue(100)
        p.addRow("Histogram bins", self.bins_spin)
        self.noisy_pct_spin = QDoubleSpinBox()
        self.noisy_pct_spin.setRange(0.0, 100.0)
        self.noisy_pct_spin.setValue(98.0)
        self.noisy_pct_spin.setSuffix(" %")
        p.addRow("Noisy-pixel percentile", self.noisy_pct_spin)

        self.valid_range = _OptionalRange("Valid range")
        p.addRow(self.valid_range)
        self.linearity_range = _OptionalRange("Linearity range")
        p.addRow(self.linearity_range)
        self.hist_range = _OptionalRange("Histogram range")
        p.addRow(self.hist_range)

        self.correct_brightness_check = QCheckBox("Correct brightness fluctuation")
        self.correct_brightness_check.setChecked(True)
        p.addRow(self.correct_brightness_check)
        self.correct_offset_check = QCheckBox("Correct offset drift")
        self.correct_offset_check.setChecked(True)
        p.addRow(self.correct_offset_check)
        self.exclude_hotcold_check = QCheckBox("Exclude hot/cold pixels")
        self.exclude_hotcold_check.setChecked(True)
        p.addRow(self.exclude_hotcold_check)
        self.brightness_blur_check = QCheckBox("Blur brightness estimate (sCMOS)")
        self.brightness_blur_check.setChecked(True)
        p.addRow(self.brightness_blur_check)
        self.plot_bg_offset_check = QCheckBox("Plot with background offset")
        self.plot_bg_offset_check.setChecked(True)
        p.addRow(self.plot_bg_offset_check)
        self.plot_hist_check = QCheckBox("Overlay brightness histogram")
        p.addRow(self.plot_hist_check)
        self.check_bg_check = QCheckBox("Verify background is flat")
        p.addRow(self.check_bg_check)
        self.saturation_check = QCheckBox("Estimate saturation / dynamic range")
        p.addRow(self.saturation_check)
        layout.addWidget(params_box)

        # -- export (optional) ---------------------------------------------------
        export_box = QGroupBox("Export (optional)")
        exp = QFormLayout(export_box)
        exp_row = QHBoxLayout()
        self.export_edit = QLineEdit()
        self.export_edit.setPlaceholderText("leave empty to skip saving")
        exp_row.addWidget(self.export_edit)
        exp_btn = QPushButton("Browse…")
        exp_btn.clicked.connect(self._browse_export)
        exp_row.addWidget(exp_btn)
        exp_w = QWidget()
        exp_w.setLayout(exp_row)
        exp.addRow("Folder", exp_w)
        self.export_format_combo = QComboBox()
        self.export_format_combo.addItems(["png", "svg"])
        exp.addRow("Format", self.export_format_combo)
        layout.addWidget(export_box)

        # -- run ------------------------------------------------------------------
        self.run_btn = QPushButton("Run calibration")
        self.run_btn.clicked.connect(self._on_run)
        layout.addWidget(self.run_btn)

        self.status = QLabel("Idle.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.results_edit = QTextEdit()
        self.results_edit.setReadOnly(True)
        self.results_edit.setMaximumHeight(160)
        layout.addWidget(self.results_edit)

        layout.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        self._refresh_layers()
        if self.viewer is not None:
            self.viewer.layers.events.inserted.connect(lambda *_: self._refresh_layers())
            self.viewer.layers.events.removed.connect(lambda *_: self._refresh_layers())
            self.viewer.layers.events.reordered.connect(lambda *_: self._refresh_layers())

    # -- layer helpers ------------------------------------------------------------
    def _refresh_layers(self) -> None:
        import napari

        names = []
        if self.viewer is not None:
            names = [
                layer.name for layer in self.viewer.layers
                if isinstance(layer, napari.layers.Image)
            ]
        for combo in (self.fg_combo, self.bg_combo):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if current in names:
                combo.setCurrentText(current)
            combo.blockSignals(False)
        # Qt auto-selects index 0 in both combos when first populated, so fg
        # and bg start out pointing at the same layer; default them apart to
        # the last two image layers whenever that happens.
        if len(names) >= 2 and self.fg_combo.currentText() == self.bg_combo.currentText():
            self.fg_combo.setCurrentText(names[-2])
            self.bg_combo.setCurrentText(names[-1])

    def _browse_export(self) -> None:
        start = self.export_edit.text() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Export folder", start)
        if chosen:
            self.export_edit.setText(chosen)

    # -- run ------------------------------------------------------------------------
    def _params_from_ui(self) -> ReadnoiseParams:
        return ReadnoiseParams(
            numBins=self.bins_spin.value(),
            validRange=self.valid_range.value(),
            linearity_range=self.linearity_range.value(),
            histRange=self.hist_range.value(),
            CameraName=self.camera_edit.text().strip() or None,
            correctBrightness=self.correct_brightness_check.isChecked(),
            correctOffsetDrift=self.correct_offset_check.isChecked(),
            exclude_hot_cold_pixels=self.exclude_hotcold_check.isChecked(),
            noisy_pixel_percentile=self.noisy_pct_spin.value(),
            brightness_blurring=self.brightness_blur_check.isChecked(),
            plotWithBgOffset=self.plot_bg_offset_check.isChecked(),
            plotHist=self.plot_hist_check.isChecked(),
            check_bg=self.check_bg_check.isChecked(),
            saturationImage=self.saturation_check.isChecked(),
            exportpath=self.export_edit.text().strip() or None,
            exportFormat=self.export_format_combo.currentText(),
        )

    def _on_run(self) -> None:
        if self.viewer is None:
            self.status.setText("No napari viewer available.")
            return
        fg_name = self.fg_combo.currentText()
        bg_name = self.bg_combo.currentText()
        if not fg_name or not bg_name:
            self.status.setText("Choose a foreground and a background stack.")
            return
        if fg_name == bg_name:
            self.status.setText("Foreground and background must be different layers.")
            return
        try:
            fg_layer = self.viewer.layers[fg_name]
            bg_layer = self.viewer.layers[bg_name]
        except KeyError as exc:
            self.status.setText(f"Layer not found: {exc}")
            return

        import numpy as np

        params = self._params_from_ui()
        self.run_btn.setEnabled(False)
        self.status.setText("Running calibration…")
        try:
            result = run_cal_readnoise(
                np.asarray(fg_layer.data), np.asarray(bg_layer.data), params
            )
        except Exception as exc:
            self.status.setText(f"<span style='color:#c0392b'>Error: {exc}</span>")
            self.run_btn.setEnabled(True)
            return
        self.run_btn.setEnabled(True)

        self.status.setText(
            f"Done — gain={result.gain:.4f} e-/ADU, "
            f"readnoise={result.readnoise:.2f} e- RMS, offset={result.offset:.2f} ADU"
        )
        self.results_edit.setPlainText(
            "\n".join(f"{k}: {v[0]}" for k, v in result.doc.items())
        )
        self._show_figures(result.figures, title=f"Read-noise calibration — {fg_name} / {bg_name}")

    # -- figure display -----------------------------------------------------------
    def _show_figures(self, figures, title: str) -> None:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.resize(1000, 700)
        tabs = QTabWidget(dlg)
        for fig, name in figures:
            canvas = FigureCanvasQTAgg(fig)
            tabs.addTab(canvas, name)
        v = QVBoxLayout(dlg)
        v.addWidget(tabs)
        # Keep a Python-side reference so the dialog isn't garbage-collected
        # out from under Qt while open; closed dialogs just linger here
        # harmlessly until this widget itself is destroyed.
        self._plot_windows.append(dlg)
        dlg.show()
