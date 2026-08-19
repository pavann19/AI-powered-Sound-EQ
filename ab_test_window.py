"""
Floating window for the blind A/B listening test (ab_test.ABTestSession).

Kept as a separate top-level window rather than a panel wedged into the
already-packed main layout, since it needs to be glanceable while you're
listening and doesn't need to compete for space with the live spectrum.
"""

import math

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy

import ui_theme as T
from ab_test import ABTestSession, MIN_SAMPLES_FOR_VERDICT


class RingTimer(QWidget):
    """Circular countdown for the current round's blind listening window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 96)
        self._frac = 0.0        # 0..1 remaining
        self._label = "—"
        self._pending = False
        self._pulse = 0.0

    def set_state(self, frac: float, label: str, pending: bool):
        self._frac = max(0.0, min(1.0, frac))
        self._label = label
        self._pending = pending
        self.update()

    def on_tick(self, dt: float):
        if self._pending:
            self._pulse += dt
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r = QRectF(6, 6, self.width() - 12, self.height() - 12)
        p.setPen(QPen(QColor(255, 255, 255, 22), 7))
        p.drawEllipse(r)

        col = T.ACCENT if not self._pending else T.POSITIVE
        alpha = 1.0
        if self._pending:
            alpha = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse * 4.0))
        pen_col = QColor(col)
        pen_col.setAlphaF(alpha)
        p.setPen(QPen(pen_col, 7, Qt.SolidLine, Qt.RoundCap))
        span = int(-360 * 16 * self._frac) if not self._pending else -360 * 16
        p.drawArc(r, 90 * 16, span)

        p.setFont(T.mono_font(15, QFont.Weight.DemiBold))
        p.setPen(QPen(T.TEXT_PRIMARY))
        p.drawText(self.rect(), Qt.AlignCenter, self._label)


class RatingButton(QWidget):
    """Custom-painted button so it matches the rest of the app instead of a
    default Qt push button."""

    def __init__(self, text: str, accent: QColor, parent=None):
        super().__init__(parent)
        self._text = text
        self._accent = accent
        self._enabled_visual = True
        self._hover = False
        self.setFixedHeight(52)
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = None

    def set_on_click(self, fn):
        self._on_click = fn

    def set_enabled_visual(self, enabled: bool):
        self._enabled_visual = enabled
        self.setEnabled(enabled)
        self.update()

    def enterEvent(self, _):
        self._hover = True
        self.update()

    def leaveEvent(self, _):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if self._enabled_visual and self._on_click:
            self._on_click()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, T.RADIUS_CONTROL, T.RADIUS_CONTROL)

        if not self._enabled_visual:
            p.fillPath(path, QBrush(QColor(255, 255, 255, 6)))
            p.setPen(QPen(T.STROKE_CONTROL, 1))
            p.drawPath(path)
            p.setPen(QPen(T.TEXT_DISABLED))
        else:
            fill = QColor(self._accent)
            fill.setAlpha(46 if self._hover else 30)
            p.fillPath(path, QBrush(fill))
            p.setPen(QPen(self._accent, 1.2))
            p.drawPath(path)
            p.setPen(QPen(self._accent))

        p.setFont(T.ui_font(10.5, QFont.Weight.DemiBold))
        p.drawText(self.rect(), Qt.AlignCenter, self._text)


class ABTestWindow(QWidget):
    def __init__(self, session: ABTestSession, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        self.session = session
        self.setWindowTitle("Blind A/B Test")
        self.setMinimumWidth(320)
        self.setMaximumWidth(320)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(14)

        self._title = QLabelPainted("Blind A/B Test", 12, True)
        outer.addWidget(self._title)

        self._explainer = QLabelPainted(
            "Randomly flips EQ on/off without telling you which. Rate what "
            "you hear each round — the state is only revealed in the results.",
            8.5, False, wrap=True, color=T.TEXT_TERTIARY,
        )
        outer.addWidget(self._explainer)

        ring_row = QHBoxLayout()
        ring_row.addStretch(1)
        self.ring = RingTimer()
        ring_row.addWidget(self.ring)
        ring_row.addStretch(1)
        outer.addLayout(ring_row)

        self._round_label = QLabelPainted("Press Start to begin", 9, False, center=True)
        outer.addWidget(self._round_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.btn_bad = RatingButton("👎 Sounds off", T.NEGATIVE)
        self.btn_bad.set_on_click(lambda: self._rate(False))
        self.btn_good = RatingButton("👍 Sounds good", T.POSITIVE)
        self.btn_good.set_on_click(lambda: self._rate(True))
        btn_row.addWidget(self.btn_bad)
        btn_row.addWidget(self.btn_good)
        outer.addLayout(btn_row)
        self._set_rating_enabled(False)

        self.start_btn = RatingButton("Start Test", T.ACCENT)
        self.start_btn.set_on_click(self._toggle_start_stop)
        outer.addWidget(self.start_btn)

        self._summary = QLabelPainted("No trials yet", 8.5, False, wrap=True, color=T.TEXT_SECONDARY)
        outer.addWidget(self._summary)
        outer.addStretch(1)

        self._render_summary()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(100)

    def _set_rating_enabled(self, enabled: bool):
        self.btn_bad.set_enabled_visual(enabled)
        self.btn_good.set_enabled_visual(enabled)

    def _toggle_start_stop(self):
        if self.session.active:
            self.session.stop()
            self.start_btn._text = "Start Test"
            self.start_btn._accent = T.ACCENT
            self._round_label.set_text("Press Start to begin")
            self._set_rating_enabled(False)
            self.ring.set_state(0.0, "—", False)
        else:
            self.session.start()
            self.start_btn._text = "Stop Test"
            self.start_btn._accent = T.CRITICAL
        self.start_btn.update()
        self._render_summary()

    def _rate(self, approved: bool):
        self.session.rate(approved)
        self._set_rating_enabled(False)
        self._render_summary()

    def _tick(self):
        if not self.session.active:
            return
        remaining = self.session.tick()
        frac = remaining / self.session.round_seconds if self.session.round_seconds else 0.0

        if self.session.pending_rating:
            self.ring.set_state(0.0, "?", True)
            self._round_label.set_text(f"Round {self.session.round_index} — how did that sound?")
            self._set_rating_enabled(True)
        else:
            self.ring.set_state(frac, f"{remaining:0.0f}s", False)
            self._round_label.set_text(f"Round {self.session.round_index} — listening…")
            self._set_rating_enabled(False)
        self.ring.on_tick(0.1)

    def _render_summary(self):
        s = self.session.summary()
        if s["total"] == 0:
            self._summary.set_text("No trials yet")
        else:
            eq_pct = f"{s['eq_rate']*100:.0f}%" if s["eq_rate"] is not None else "—"
            by_pct = f"{s['bypass_rate']*100:.0f}%" if s["bypass_rate"] is not None else "—"
            need = MIN_SAMPLES_FOR_VERDICT
            text = (
                f"EQ on: {eq_pct} approved ({s['eq_n']} rounds)\n"
                f"Bypass: {by_pct} approved ({s['bypass_n']} rounds)\n"
                f"Verdict: {s['verdict']}"
            )
            if s["eq_n"] < need or s["bypass_n"] < need:
                text += f"\n(need {need}+ rounds each condition for a verdict)"
            self._summary.set_text(text)
        # The summary's line count varies (grows once the verdict caveat
        # appears), so its own minimum height changes -- adjustSize() lets
        # the window grow/shrink to fit rather than clipping the extra line.
        self.adjustSize()

    def closeEvent(self, e):
        # Hide rather than destroy -- keeps the running session alive if the
        # user reopens it, and stops audio from being stranded mid-round.
        if self.session.active:
            self.session.stop()
            self.start_btn._text = "Start Test"
            self.start_btn._accent = T.ACCENT
        e.accept()


class QLabelPainted(QWidget):
    """Small custom label so text styling matches the rest of the app's
    painted widgets instead of relying on QLabel's stylesheet system."""

    def __init__(self, text, size, bold, wrap=False, center=False, color=None, parent=None):
        super().__init__(parent)
        self._text = text
        self._size = size
        self._bold = bold
        self._wrap = wrap
        self._center = center
        self._color = color or T.TEXT_PRIMARY
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._recalc_height()

    def _font(self) -> QFont:
        return T.ui_font(self._size, QFont.Weight.DemiBold if self._bold else QFont.Weight.Normal)

    def _recalc_height(self):
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self._font())
        if self._wrap:
            # Explicit '\n' lines are the common case here (summary text is
            # built from literal newlines, not flowed prose), so count those
            # directly rather than estimating a fixed "3 lines" -- a label
            # whose content grows past that guess would otherwise get its
            # extra lines silently clipped since QPainter doesn't clip to
            # the widget rect by default.
            lines = max(3, self._text.count("\n") + 1)
            self.setMinimumHeight(fm.lineSpacing() * lines + 4)
        else:
            self.setFixedHeight(fm.height() + 4)
        self.updateGeometry()

    def set_text(self, text: str):
        if text != self._text:
            self._text = text
            self._recalc_height()
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self._font())
        p.setPen(QPen(self._color))
        flags = Qt.TextWordWrap if self._wrap else 0
        align = (Qt.AlignHCenter if self._center else Qt.AlignLeft) | Qt.AlignVCenter
        p.drawText(self.rect(), align | flags, self._text)
