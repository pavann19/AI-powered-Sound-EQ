"""
SoundIntelligence -- native Windows 11 desktop application.

Replaces the previous FastAPI + browser-window architecture. The DSP pipeline
(main.AudioProcessor) runs in its own thread exactly as before; this module is
purely the presentation layer, bridged to that thread by a Qt signal so all
widget mutation happens on the GUI thread.

Run:
    python app_native.py
"""

import sys
import os
import time
import threading

from PySide6.QtCore import Qt, QTimer, QObject, Signal, QRectF, QPointF, QSize
from PySide6.QtGui import (
    QPainter, QColor, QIcon, QPixmap, QPen, QBrush, QAction,
    QPainterPath, QLinearGradient, QFont,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QSystemTrayIcon, QMenu, QLabel, QSizePolicy,
)

import ui_theme as T
from ui_widgets import (
    SpectrumWidget, EqCurveWidget, GainRiderWidget, ClassifierWidget,
    PresetBar, StatusStrip, Card, BypassToggle,
)
from win_backdrop import apply_backdrop, supports_mica, BACKDROP_MICA_ALT
from eq_presets import PRESETS
from preference_model import MIN_SAMPLES as PREF_MIN_SAMPLES
from ab_test import ABTestSession
from ab_test_window import ABTestWindow, RatingButton

APP_NAME = "SoundIntelligence"


# ── Thread bridge ────────────────────────────────────────────────────────
class EngineBridge(QObject):
    """Marshals AudioProcessor callbacks (background thread) onto the GUI
    thread. Qt queues emissions across thread boundaries automatically, which
    is the only safe way to touch widgets from the DSP loop."""

    state_changed = Signal(dict)
    engine_ready = Signal(object)
    engine_failed = Signal(str)
    load_progress = Signal(str)


def make_app_icon(size: int = 64) -> QIcon:
    """Draw the tray/window icon at runtime: an accent-tinted waveform on a
    rounded square, matching the Win11 icon silhouette."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    r = QRectF(2, 2, size - 4, size - 4)
    path = QPainterPath()
    path.addRoundedRect(r, size * 0.22, size * 0.22)
    grad = QLinearGradient(r.topLeft(), r.bottomRight())
    grad.setColorAt(0.0, QColor(0x2A, 0x4A, 0x6B))
    grad.setColorAt(1.0, QColor(0x14, 0x20, 0x30))
    p.fillPath(path, QBrush(grad))
    p.setPen(QPen(QColor(255, 255, 255, 40), 1.5))
    p.drawPath(path)

    # Waveform bars
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(T.ACCENT))
    heights = [0.30, 0.58, 0.86, 0.62, 0.38]
    bw = size * 0.075
    gap = size * 0.055
    total = len(heights) * bw + (len(heights) - 1) * gap
    x = (size - total) / 2
    for h in heights:
        bh = size * h * 0.52
        p.drawRoundedRect(QRectF(x, (size - bh) / 2, bw, bh), bw / 2, bw / 2)
        x += bw + gap
    p.end()
    return QIcon(pm)


class TitleBar(QWidget):
    """App identity row. Sits inside the client area under the native title
    bar, carrying the brand mark, engine state and a live signal beacon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self._status = "Starting engine…"
        self._live = False
        self._pulse = 0.0
        self._cached = False

    def set_status(self, text: str, live: bool, cached: bool = False):
        self._status = text
        self._live = live
        self._cached = cached
        self.update()

    def on_tick(self, dt: float):
        if self._live:
            self._pulse += dt
            self.update()

    def paintEvent(self, _):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Brand mark
        icon_r = QRectF(4, 12, 32, 32)
        path = QPainterPath()
        path.addRoundedRect(icon_r, 8, 8)
        grad = QLinearGradient(icon_r.topLeft(), icon_r.bottomRight())
        grad.setColorAt(0.0, QColor(0x2A, 0x4A, 0x6B))
        grad.setColorAt(1.0, QColor(0x14, 0x20, 0x30))
        p.fillPath(path, QBrush(grad))
        p.setPen(QPen(QColor(255, 255, 255, 36), 1))
        p.drawPath(path)

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(T.ACCENT))
        for i, h in enumerate([0.34, 0.66, 0.95, 0.7, 0.42]):
            bh = 18 * h
            p.drawRoundedRect(QRectF(icon_r.left() + 6 + i * 4.4, icon_r.center().y() - bh / 2, 2.6, bh), 1.3, 1.3)

        p.setFont(T.display_font(13, QFont.Weight.DemiBold))
        p.setPen(QPen(T.TEXT_PRIMARY))
        p.drawText(QRectF(46, 12, 300, 18), Qt.AlignLeft | Qt.AlignVCenter, APP_NAME)

        p.setFont(T.ui_font(8.5))
        p.setPen(QPen(T.TEXT_TERTIARY))
        p.drawText(QRectF(46, 29, 400, 16), Qt.AlignLeft | Qt.AlignVCenter, self._status)

        # Live beacon (right aligned)
        bx = self.width() - 16
        label = "LIVE" if self._live else "IDLE"
        if self._cached:
            label = "RECALLED"
        p.setFont(T.ui_font(8, QFont.Weight.DemiBold))
        fm_w = p.fontMetrics().horizontalAdvance(label)

        pill = QRectF(bx - fm_w - 30, 18, fm_w + 30, 22)
        pp = QPainterPath()
        pp.addRoundedRect(pill, 11, 11)
        p.fillPath(pp, QBrush(T.SURFACE_CONTROL))
        p.setPen(QPen(T.STROKE_CONTROL, 1))
        p.drawPath(pp)

        col = T.ACCENT if self._cached else (T.POSITIVE if self._live else T.TEXT_DISABLED)
        alpha = 1.0
        if self._live:
            alpha = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse * 3.2))
        dot = QColor(col)
        dot.setAlphaF(alpha)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(dot))
        p.drawEllipse(QPointF(pill.left() + 12, pill.center().y()), 3.5, 3.5)

        p.setPen(QPen(T.TEXT_SECONDARY))
        p.drawText(QRectF(pill.left() + 20, pill.top(), pill.width() - 26, pill.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, label)


class MainWindow(QMainWindow):
    def __init__(self, bridge: EngineBridge):
        super().__init__()
        self.bridge = bridge
        self.processor = None
        self._mica = False
        self._last_tick = time.perf_counter()
        self._quitting = False
        self.ab_test_session = None
        self.ab_test_window = None

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_app_icon())
        self.resize(1140, 880)
        self.setMinimumSize(QSize(940, 730))

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 8, 16, 12)
        outer.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        self.titlebar = TitleBar()
        header_row.addWidget(self.titlebar, stretch=1)
        self.bypass_toggle = BypassToggle()
        self.bypass_toggle.toggled.connect(self.on_bypass_toggled)
        header_row.addWidget(self.bypass_toggle, stretch=0, alignment=Qt.AlignVCenter)

        self.ab_test_btn = RatingButton("Blind Test", T.ACCENT)
        self.ab_test_btn.setFixedWidth(110)
        self.ab_test_btn.set_on_click(self.open_ab_test_window)
        header_row.addWidget(self.ab_test_btn, stretch=0, alignment=Qt.AlignVCenter)

        outer.addLayout(header_row)

        self.spectrum = SpectrumWidget()
        outer.addWidget(self.spectrum, stretch=5)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.classifier = ClassifierWidget()
        self.curve = EqCurveWidget()
        self.rider = GainRiderWidget()
        grid.addWidget(self.classifier, 0, 0)
        grid.addWidget(self.curve, 0, 1)
        grid.addWidget(self.rider, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 2)
        outer.addLayout(grid, stretch=7)

        self.presetbar = PresetBar(PRESETS)
        self.presetbar.selected.connect(self.on_preset_selected)
        outer.addWidget(self.presetbar)

        self.status = StatusStrip()
        outer.addWidget(self.status)

        self._animated = [
            self.titlebar, self.spectrum, self.classifier,
            self.curve, self.rider, self.presetbar, self.bypass_toggle,
        ]

        # 60fps render loop -- widgets interpolate toward targets here.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_frame)
        self.timer.start(16)

        bridge.state_changed.connect(self.on_state)
        bridge.engine_ready.connect(self.on_engine_ready)
        bridge.engine_failed.connect(self.on_engine_failed)
        bridge.load_progress.connect(self.on_load_progress)

        self.status.set_items([
            ("Engine", "Initialising", T.TEXT_TERTIARY),
            ("Profile", "—", None),
            ("Switch dwell", "—", None),
            ("Recall", "—", None),
            ("Personalization", "—", None),
        ])

    # ── Window chrome ────────────────────────────────────────────────
    def showEvent(self, e):
        super().showEvent(e)
        if not self._mica:
            self._mica = apply_backdrop(self, BACKDROP_MICA_ALT, dark=True)

    def paintEvent(self, e):
        """When DWM gives us Mica the window background must stay transparent
        so the compositor's material shows through. Without it we paint our
        own dark base."""
        p = QPainter(self)
        if not self._mica:
            p.fillRect(self.rect(), QColor(0x1C, 0x1C, 0x20))
        else:
            p.fillRect(self.rect(), QColor(0x00, 0x00, 0x00, 1))
        super().paintEvent(e)

    # ── Frame loop ───────────────────────────────────────────────────
    def on_frame(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last_tick)
        self._last_tick = now
        for w in self._animated:
            w.on_tick(dt)

    # ── Engine lifecycle ─────────────────────────────────────────────
    def on_load_progress(self, msg: str):
        self.titlebar.set_status(msg, False)

    def on_engine_ready(self, processor):
        self.processor = processor
        self.titlebar.set_status("Analysing system audio", True)
        # A user could flip the toggle before the engine finished loading
        # YAMNet; apply whatever they landed on now that there's a processor.
        if self.bypass_toggle.is_bypassed():
            processor.set_bypass(True)
        self.ab_test_session = ABTestSession(processor)

    def open_ab_test_window(self):
        if not self.ab_test_session:
            return  # engine still loading -- nothing to test against yet
        if self.ab_test_window is None:
            self.ab_test_window = ABTestWindow(self.ab_test_session, self)
        self.ab_test_window.show()
        self.ab_test_window.raise_()
        self.ab_test_window.activateWindow()

    def on_engine_failed(self, err: str):
        self.titlebar.set_status(f"Engine failed: {err}", False)
        self.status.set_items([
            ("Engine", "Failed", T.CRITICAL),
            ("Detail", err[:60], T.CRITICAL),
            ("Backdrop", "Mica" if self._mica else "Solid", None),
            ("Recall", "—", None),
        ])

    def on_preset_selected(self, preset_id: str):
        if not self.processor:
            return
        # Routed through set_manual_override rather than a plain attribute
        # assignment -- that's the hook that logs this pick as a labeled
        # example for the preference model.
        self.processor.set_manual_override(None if preset_id == "auto" else preset_id)

    def on_bypass_toggled(self, bypassed: bool):
        if self.processor:
            self.processor.set_bypass(bypassed)
        # If there's no processor yet, the toggle's own state still updates;
        # on_engine_ready() applies it once the DSP thread exists.

    # ── State ingest ─────────────────────────────────────────────────
    def on_state(self, s: dict):
        silent = bool(s.get("silent", False))
        self.spectrum.set_spectrum(s.get("spectral", {}), silent)
        self.rider.set_adjustments(s.get("dynamic_adjustments", {}))
        self.classifier.set_predictions(s.get("ml_predictions", []))
        self.curve.set_filters(s.get("filters", []))
        self.curve.set_bypassed(bool(s.get("bypass")))

        preds = s.get("ml_predictions") or []
        current = s.get("current_preset")
        cached = bool(s.get("is_cached"))
        bypassed = bool(s.get("bypass"))
        # The backend is the source of truth (it may have been toggled before
        # the GUI's own toggle existed, or diverge if the state is stale).
        self.bypass_toggle.set_bypassed(bypassed, animate=False)
        ab_active = bool(self.ab_test_session and self.ab_test_session.active)
        self.bypass_toggle.set_locked(ab_active, "Blind test running" if ab_active else "")

        if silent:
            self.spectrum.set_classification("Silent", "No audio on the output device", 0.0)
        elif preds:
            top = preds[0]
            meta = PRESETS.get(current, {})
            self.spectrum.set_classification(
                top["class_name"],
                f"{meta.get('name', 'Analysing')} · {meta.get('description', '')}",
                float(top.get("confidence", 0.0)),
            )
        else:
            self.spectrum.set_classification("Analysing…", "Building first prediction window", 0.0)

        if bypassed:
            status_text = "Bypassed — playing unprocessed"
        elif cached:
            status_text = "Recalled from fingerprint cache"
        else:
            status_text = "Analysing system audio"
        self.titlebar.set_status(status_text, not silent, cached and not bypassed)

        if current:
            self.presetbar.set_auto_resolved(PRESETS.get(current, {}).get("name", current))

        override = self.processor.manual_override if self.processor else None
        self.presetbar.set_active(override or "auto")

        fp_ok = s.get("fingerprint_available")
        dwell = self.processor.min_dwell_seconds if self.processor else None
        pref_ready = bool(s.get("preference_ready"))
        pref_samples = int(s.get("preference_samples", 0))
        if pref_ready:
            pref_text = f"Active · {pref_samples} picks"
        elif pref_samples:
            pref_text = f"{pref_samples}/{PREF_MIN_SAMPLES} picks"
        else:
            pref_text = "Override a preset to teach it"
        self.status.set_items([
            ("Engine", "Silent" if silent else "Active",
             T.TEXT_TERTIARY if silent else T.POSITIVE),
            ("Profile", PRESETS.get(current, {}).get("name", "—"), T.ACCENT if current else None),
            ("Switch dwell", f"{dwell:.0f}s minimum" if dwell else "—", None),
            ("Recall", ("Cache hit" if cached else "Learning") if fp_ok else "Unavailable",
             T.ACCENT if cached else None),
            ("Personalization", pref_text, T.ACCENT if pref_ready else None),
        ])

    # ── Close / tray ─────────────────────────────────────────────────
    def closeEvent(self, e):
        """Closing hides to tray -- the DSP is meant to keep running. Real
        exit goes through the tray menu."""
        if self._quitting:
            e.accept()
            return
        e.ignore()
        self.hide()

    def really_quit(self):
        self._quitting = True
        if self.processor:
            try:
                self.processor.stop()
            except Exception:
                pass
        self.close()
        QApplication.quit()


def start_engine(bridge: EngineBridge):
    """Construct and start the DSP pipeline off the GUI thread.

    AudioProcessor.__init__ loads YAMNet, which takes seconds and would
    otherwise freeze the window before it ever painted.
    """
    try:
        bridge.load_progress.emit("Loading neural classifier…")
        from main import AudioProcessor  # imported here: pulls in TensorFlow

        processor = AudioProcessor()
        processor.on_update(lambda state: bridge.state_changed.emit(state))

        bridge.load_progress.emit("Opening loopback capture…")
        processor.start()
        bridge.engine_ready.emit(processor)
    except Exception as e:
        bridge.engine_failed.emit(str(e))


def main():
    # High-DPI pixmaps are always on in Qt 6, so no attribute setup is needed.
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(T.ui_font(10))

    bridge = EngineBridge()
    win = MainWindow(bridge)

    icon = make_app_icon()
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip(f"{APP_NAME} — adaptive EQ running")

    # Parented to the window so Python's GC can't collect it out from under
    # the tray icon (setContextMenu does not take ownership in PySide).
    menu = QMenu(win)
    act_show = QAction("Open SoundIntelligence", menu)
    act_show.triggered.connect(lambda: (win.showNormal(), win.raise_(), win.activateWindow()))
    menu.addAction(act_show)
    menu.addSeparator()

    act_autostart = QAction("Start with Windows", menu)
    act_autostart.setCheckable(True)
    try:
        from autostart_manager import is_autostart_enabled, set_autostart
        act_autostart.setChecked(is_autostart_enabled())

        def toggle_autostart(checked: bool):
            ok = set_autostart(checked)
            if not ok:
                # Revert with signals blocked, otherwise setChecked re-enters
                # this handler and fires a second, contradictory toast.
                act_autostart.blockSignals(True)
                act_autostart.setChecked(is_autostart_enabled())
                act_autostart.blockSignals(False)
            tray.showMessage(
                APP_NAME,
                f"Start with Windows {'enabled' if checked else 'disabled'}"
                if ok else "Could not change the startup entry",
                QSystemTrayIcon.MessageIcon.Information, 2500,
            )

        act_autostart.toggled.connect(toggle_autostart)
        menu.addAction(act_autostart)
        menu.addSeparator()
    except Exception:
        pass  # autostart is a convenience -- never block startup on it

    act_quit = QAction("Exit", menu)
    act_quit.triggered.connect(win.really_quit)
    menu.addAction(act_quit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: (win.showNormal(), win.raise_(), win.activateWindow())
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
    )
    tray.show()

    win.show()

    threading.Thread(target=start_engine, args=(bridge,), daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
