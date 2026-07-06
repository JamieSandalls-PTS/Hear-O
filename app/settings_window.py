"""Settings window opened via the global hotkey or the tray icon.

Every control writes straight into the Settings object and calls back so the
overlay updates live. A preview is shown by putting the HUD into demo mode
while this window is open.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QSlider, QCheckBox, QComboBox, QPushButton, QDoubleSpinBox, QSpinBox,
    QScrollArea, QInputDialog, QMessageBox,
)


def _slider(minimum, maximum, value, on_change):
    s = QSlider(Qt.Horizontal)
    s.setMinimum(minimum)
    s.setMaximum(maximum)
    s.setValue(int(value))
    s.valueChanged.connect(on_change)
    return s


class SettingsWindow(QWidget):
    def __init__(self, settings, on_apply, audio_engine=None, on_hide=None,
                 classifier=None):
        super().__init__()
        self.settings = settings
        self.on_apply = on_apply
        self.audio_engine = audio_engine
        self.classifier = classifier
        self.on_hide = on_hide  # called whenever the window becomes hidden

        self.setWindowTitle("Hear-O - Settings")
        self.setMinimumWidth(440)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        # A fixed outer layout holds one swappable container widget, so a full
        # rebuild (after a preset load) just replaces that container.
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._container = None
        self._build_ui()

    def _build_ui(self):
        container = QWidget()
        wrap = QVBoxLayout(container)
        wrap.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(container)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        root = QVBoxLayout(inner)

        self.status_label = QLabel("Audio: starting...")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        root.addWidget(self._build_presets_group())
        root.addWidget(self._build_device_group())
        root.addWidget(self._build_analysis_group())
        root.addWidget(self._build_classification_group())
        root.addWidget(self._build_subtitles_group())
        root.addWidget(self._build_layout_group())
        root.addWidget(self._build_bands_group())
        root.addWidget(self._build_hotkey_note())

        buttons = QHBoxLayout()
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset_defaults)
        close = QPushButton("Close")
        close.clicked.connect(self.hide)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(close)
        root.addLayout(buttons)

        wrap.addWidget(scroll)
        self._outer.addWidget(container)
        self._container = container
        self.resize(480, 680)

    def _rebuild(self):
        """Replace the whole UI container (after a preset load / reset)."""
        if self._container is not None:
            self._outer.removeWidget(self._container)
            self._container.setParent(None)
            self._container.deleteLater()
            self._container = None
        self._build_ui()

    # -- presets ------------------------------------------------------------
    def _build_presets_group(self):
        box = QGroupBox("Presets")
        lay = QHBoxLayout(box)
        self.preset_combo = QComboBox()
        self._refresh_presets()
        lay.addWidget(self.preset_combo, 1)
        load = QPushButton("Load")
        load.clicked.connect(self._preset_load)
        save = QPushButton("Save as...")
        save.clicked.connect(self._preset_save_as)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._preset_delete)
        lay.addWidget(load)
        lay.addWidget(save)
        lay.addWidget(delete)
        return box

    def _refresh_presets(self):
        self.preset_combo.clear()
        names = self.settings.list_presets()
        if names:
            self.preset_combo.addItems(names)
        else:
            self.preset_combo.addItem("(no presets saved)")
            self.preset_combo.setEnabled(False)
            return
        self.preset_combo.setEnabled(True)

    def _preset_load(self):
        if not self.settings.list_presets():
            return
        name = self.preset_combo.currentText()
        if self.settings.load_preset(name):
            if self.on_apply:
                self.on_apply()
            if self.audio_engine:
                self.audio_engine.restart()  # device may have changed
            self._rebuild()

    def _preset_save_as(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if ok and name.strip():
            self.settings.save_preset(name.strip())
            self._refresh_presets()
            pos = self.preset_combo.findText(name.strip())
            if pos >= 0:
                self.preset_combo.setCurrentIndex(pos)

    def _preset_delete(self):
        if not self.settings.list_presets():
            return
        name = self.preset_combo.currentText()
        confirm = QMessageBox.question(
            self, "Delete preset", f"Delete preset '{name}'?")
        if confirm == QMessageBox.Yes:
            self.settings.delete_preset(name)
            self._refresh_presets()

    # -- groups -------------------------------------------------------------
    def _build_device_group(self):
        box = QGroupBox("Audio device")
        lay = QVBoxLayout(box)
        self.device_combo = QComboBox()
        self.device_combo.addItem("Default output (follow Windows)", None)
        if self.audio_engine:
            for idx, name in self.audio_engine.list_loopback_devices():
                self.device_combo.addItem(name, idx)
        current = self.settings.get("audio.device_index", None)
        pos = self.device_combo.findData(current)
        if pos >= 0:
            self.device_combo.setCurrentIndex(pos)
        self.device_combo.currentIndexChanged.connect(self._device_changed)
        lay.addWidget(QLabel("Capture from:"))
        lay.addWidget(self.device_combo)
        hint = QLabel("Tip: set Windows and the game to 7.1 surround for true "
                      "front/back direction. Stereo gives left/right + intensity.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        lay.addWidget(hint)
        return box

    def _build_analysis_group(self):
        box = QGroupBox("Sensitivity")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Sensitivity"), 0, 0)
        self.sens_val = QLabel()
        grid.addWidget(self.sens_val, 0, 2)
        s = _slider(20, 300, self.settings.get("analysis.sensitivity", 1.0) * 100,
                    self._sensitivity_changed)
        grid.addWidget(s, 0, 1)

        grid.addWidget(QLabel("Noise gate"), 1, 0)
        self.gate_val = QLabel()
        grid.addWidget(self.gate_val, 1, 2)
        g = _slider(0, 60, self.settings.get("analysis.noise_gate", 0.06) * 100,
                    self._gate_changed)
        grid.addWidget(g, 1, 1)

        grid.addWidget(QLabel("Smoothing"), 2, 0)
        self.smooth_val = QLabel()
        grid.addWidget(self.smooth_val, 2, 2)
        m = _slider(0, 99, self.settings.get("analysis.smoothing", 0.5) * 100,
                    self._smoothing_changed)
        grid.addWidget(m, 2, 1)

        self._refresh_analysis_labels()
        return box

    def _build_classification_group(self):
        box = QGroupBox("Sound recognition (AI)")
        lay = QVBoxLayout(box)

        self.class_enable = QCheckBox(
            "Recognise sound types (footsteps, gunshot, speech, ...)")
        self.class_enable.setChecked(self.settings.get("classification.enabled", True))
        self.class_enable.toggled.connect(
            lambda v: self._set("classification.enabled", v))
        lay.addWidget(self.class_enable)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Detail"))
        self.class_mode = QComboBox()
        self.class_mode.addItem("Detailed (widest variety)", "detailed")
        self.class_mode.addItem("Grouped (~40 tidy categories)", "grouped")
        pos = self.class_mode.findData(
            self.settings.get("classification.mode", "detailed"))
        if pos >= 0:
            self.class_mode.setCurrentIndex(pos)
        self.class_mode.currentIndexChanged.connect(
            lambda: self._set("classification.mode", self.class_mode.currentData()))
        mode_row.addWidget(self.class_mode, 1)
        lay.addLayout(mode_row)

        self.boost_cb = QCheckBox("Boost soft sounds (helps quiet footsteps)")
        self.boost_cb.setChecked(self.settings.get("classification.boost_soft", True))
        self.boost_cb.toggled.connect(
            lambda v: self._set("classification.boost_soft", v))
        lay.addWidget(self.boost_cb)

        row = QHBoxLayout()
        row.addWidget(QLabel("Detection threshold"))
        thr = _slider(10, 80, self.settings.get("classification.threshold", 0.35) * 100,
                      self._threshold_changed)
        self.thresh_val = QLabel()
        row.addWidget(thr)
        row.addWidget(self.thresh_val)
        lay.addLayout(row)

        self.class_status_label = QLabel("")
        self.class_status_label.setWordWrap(True)
        if self.classifier is not None:
            self.class_status_label.setText(self.classifier.status)
        lay.addWidget(self.class_status_label)

        note = QLabel("Recognises ~500 sound types locally (~2 ms per check). "
                      "'Detailed' shows the widest variety of labels; 'Grouped' "
                      "tidies them into ~40 categories. Direction is borrowed "
                      "from each sound's frequency band, so it is approximate.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888;")
        lay.addWidget(note)

        self._refresh_class_labels()
        return box

    def _build_subtitles_group(self):
        box = QGroupBox("Speech subtitles (AI)")
        lay = QVBoxLayout(box)

        self.sub_enable = QCheckBox("Show live subtitles for speech")
        self.sub_enable.setChecked(self.settings.get("subtitles.enabled", True))
        self.sub_enable.toggled.connect(
            lambda v: self._set("subtitles.enabled", v))
        lay.addWidget(self.sub_enable)

        row = QHBoxLayout()
        row.addWidget(QLabel("Model"))
        self.sub_model = QComboBox()
        for m in ["tiny.en", "base.en", "small.en"]:
            self.sub_model.addItem(m, m)
        pos = self.sub_model.findData(self.settings.get("subtitles.model", "base.en"))
        if pos >= 0:
            self.sub_model.setCurrentIndex(pos)
        self.sub_model.currentIndexChanged.connect(self._sub_model_changed)
        row.addWidget(self.sub_model)
        lay.addLayout(row)

        self.sub_status_label = QLabel("")
        self.sub_status_label.setWordWrap(True)
        lay.addWidget(self.sub_status_label)

        note = QLabel("Uses the speech detector, so keep sound recognition on. "
                      "tiny = fastest, small = most accurate. Changing the model "
                      "applies on restart. First use downloads the model once.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888;")
        lay.addWidget(note)
        return box

    def _build_layout_group(self):
        box = QGroupBox("Overlay layout")
        grid = QGridLayout(box)
        ov = self.settings.data["overlay"]

        rows = [
            ("Horizontal position", "center_x", 0, 100, 100),
            ("Vertical position", "center_y", 0, 100, 100),
            ("Ring size", "base_radius", 30, 300, 1),
            ("Ring spacing", "ring_spacing", 10, 80, 1),
            ("Arc thickness", "thickness", 4, 40, 1),
            ("Label text size", "label_font_size", 7, 32, 1),
            ("Label fade (s)", "label_fade", 0, 50, 10),
            ("Opacity", "opacity", 20, 100, 100),
        ]
        self._layout_labels = {}
        for r, (label, key, lo, hi, scale) in enumerate(rows):
            grid.addWidget(QLabel(label), r, 0)
            val_lbl = QLabel()
            self._layout_labels[key] = (val_lbl, scale)
            grid.addWidget(val_lbl, r, 2)
            init = ov[key] * scale
            sld = _slider(lo, hi, init,
                          lambda v, k=key, sc=scale: self._layout_changed(k, v, sc))
            grid.addWidget(sld, r, 1)

        row = len(rows)
        self.compass_cb = QCheckBox("Show F/B/L/R compass")
        self.compass_cb.setChecked(ov.get("show_compass", True))
        self.compass_cb.toggled.connect(lambda v: self._set("overlay.show_compass", v))
        grid.addWidget(self.compass_cb, row, 0, 1, 3)

        self.labels_cb = QCheckBox("Show sound labels")
        self.labels_cb.setChecked(ov.get("show_labels", True))
        self.labels_cb.toggled.connect(lambda v: self._set("overlay.show_labels", v))
        grid.addWidget(self.labels_cb, row + 1, 0, 1, 3)

        self.click_cb = QCheckBox("Click-through (let clicks reach the game)")
        self.click_cb.setChecked(ov.get("click_through", True))
        self.click_cb.toggled.connect(lambda v: self._set("overlay.click_through", v))
        grid.addWidget(self.click_cb, row + 2, 0, 1, 3)

        self._refresh_layout_labels()
        return box

    def _build_bands_group(self):
        box = QGroupBox("Sound indicators (frequency bands)")
        lay = QVBoxLayout(box)
        for i, band in enumerate(self.settings.get("bands", [])):
            cb = QCheckBox(f"{band['name']}  -  {band.get('hint', '')}  "
                           f"({band['low_hz']}-{band['high_hz']} Hz)")
            cb.setChecked(band.get("enabled", True))
            cb.toggled.connect(lambda v, idx=i: self._band_toggled(idx, v))
            lay.addWidget(cb)
        note = QLabel("Each enabled band is a separate ring. Colour = intensity, "
                      "position = direction. Sound-type names and speech "
                      "subtitles arrive in a later update.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888;")
        lay.addWidget(note)
        return box

    def _build_hotkey_note(self):
        box = QGroupBox("Hotkey")
        lay = QVBoxLayout(box)
        hk = self.settings.get("hotkey_settings", "ctrl+alt+o")
        lay.addWidget(QLabel(f"Open settings: <b>{hk}</b>"))
        lay.addWidget(QLabel("Change it by editing config.json in your user "
                             "folder (~/.hearo), then restart."))
        return box

    # -- change handlers ----------------------------------------------------
    def _set(self, key, value):
        self.settings.set(key, value)
        self._apply()

    def _apply(self):
        self.settings.save()
        if self.on_apply:
            self.on_apply()

    def _device_changed(self):
        self.settings.set("audio.device_index", self.device_combo.currentData())
        self.settings.save()
        if self.audio_engine:
            self.audio_engine.restart()

    def _sensitivity_changed(self, v):
        self.settings.set("analysis.sensitivity", v / 100.0)
        self._refresh_analysis_labels()
        self._apply()

    def _gate_changed(self, v):
        self.settings.set("analysis.noise_gate", v / 100.0)
        self._refresh_analysis_labels()
        self._apply()

    def _smoothing_changed(self, v):
        self.settings.set("analysis.smoothing", v / 100.0)
        self._refresh_analysis_labels()
        self._apply()

    def _threshold_changed(self, v):
        self.settings.set("classification.threshold", v / 100.0)
        self._refresh_class_labels()
        self.settings.save()

    def _layout_changed(self, key, v, scale):
        self.settings.set(f"overlay.{key}", v / scale)
        self._refresh_layout_labels()
        self._apply()

    def _band_toggled(self, idx, value):
        self.settings.data["bands"][idx]["enabled"] = value
        self._apply()

    def _reset_defaults(self):
        from .config import DEFAULTS
        import copy
        self.settings.data = copy.deepcopy(DEFAULTS)
        self.settings.save()
        if self.on_apply:
            self.on_apply()
        # Rebuild the window so every control reflects the defaults.
        self._rebuild()

    # -- label refreshers ---------------------------------------------------
    def _refresh_analysis_labels(self):
        self.sens_val.setText(f"{self.settings.get('analysis.sensitivity', 1.0):.2f}x")
        self.gate_val.setText(f"{self.settings.get('analysis.noise_gate', 0.06):.2f}")
        self.smooth_val.setText(f"{self.settings.get('analysis.smoothing', 0.5):.2f}")

    def _refresh_class_labels(self):
        self.thresh_val.setText(
            f"{self.settings.get('classification.threshold', 0.35):.2f}")

    def _sub_model_changed(self):
        self.settings.set("subtitles.model", self.sub_model.currentData())
        self.settings.save()

    def set_class_status(self, text):
        if hasattr(self, "class_status_label"):
            self.class_status_label.setText(text)

    def set_sub_status(self, text):
        if hasattr(self, "sub_status_label"):
            self.sub_status_label.setText(text)

    def _refresh_layout_labels(self):
        for key, (lbl, scale) in self._layout_labels.items():
            val = self.settings.get(f"overlay.{key}")
            if scale == 100:
                lbl.setText(f"{val:.2f}")
            else:
                lbl.setText(f"{val:g}")

    def set_status(self, text):
        self.status_label.setText(f"Audio: {text}")

    def hideEvent(self, event):
        # Fires on close (X) and hide(); used to stop the overlay preview.
        if self.on_hide:
            self.on_hide()
        super().hideEvent(event)
