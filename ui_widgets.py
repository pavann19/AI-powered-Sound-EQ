"""
Custom-painted Fluent widgets for SoundIntelligence.

Everything here draws with QPainter rather than stacking styled QWidgets,
because the interesting surfaces (spectrum, EQ curve, gain meters) are
continuous data visualisations that need to animate at 60fps without
per-frame layout work.

Shared conventions:
  - Widgets never touch the audio pipeline. They expose set_*() slots and
    are driven from the GUI thread by MainWindow.
  - Every widget interpolates toward its target values in on_tick() so the
    render loop stays smooth even though audio state arrives at ~5Hz.
"""

import math
import time

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QPainterPath, QFontMetricsF, QFont,
)
from PySide6.QtWidgets import QWidget, QSizePolicy

import ui_theme as T


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class Card(QWidget):
    """Fluent 'Layer' surface: subtle translucent fill + 1px stroke, drawn so
    the Mica backdrop stays visible through it."""

    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self.setAttribute(Qt.WA_TranslucentBackground, False)

    def header_height(self) -> int:
        return 44 if self._title else 0

    def paint_surface(self, p: QPainter):
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, T.RADIUS_CARD, T.RADIUS_CARD)

        p.fillPath(path, QBrush(T.SURFACE_CARD))
        p.setPen(QPen(T.STROKE_CARD, 1))
        p.drawPath(path)

        if self._title:
            p.setFont(T.ui_font(10.5, QFont.Weight.DemiBold))
            p.setPen(QPen(T.TEXT_PRIMARY))
            p.drawText(QRectF(16, 12, self.width() - 32, 20),
                       Qt.AlignLeft | Qt.AlignVCenter, self._title)
            if self._subtitle:
                p.setFont(T.ui_font(8.5))
                p.setPen(QPen(T.TEXT_TERTIARY))
                p.drawText(QRectF(16, 12, self.width() - 32, 20),
                           Qt.AlignRight | Qt.AlignVCenter, self._subtitle)

    def set_subtitle(self, text: str):
        if text != self._subtitle:
            self._subtitle = text
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_surface(p)


class SpectrumWidget(Card):
    """The hero visualisation: a mirrored frequency-bar field with a live
    readout of what the classifier currently thinks it's hearing.

    Bars are interpolated per-frame from the 6 analysed bands into a wider
    strip so the motion reads as a spectrum rather than 6 chunky blocks.
    """

    NUM_BARS = 64

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._targets = [0.0] * self.NUM_BARS
        self._values = [0.0] * self.NUM_BARS
        self._peaks = [0.0] * self.NUM_BARS
        self._peak_hold = [0.0] * self.NUM_BARS

        self._label = "Waiting for audio"
        self._sublabel = "No signal on the capture device"
        self._confidence = 0.0
        self._silent = True
        self._phase = 0.0

    def set_spectrum(self, bands: dict, silent: bool):
        """bands: raw (unnormalised) band energies from analyzer.band_energies."""
        self._silent = silent
        vals = [max(0.0, float(bands.get(k, 0.0))) for k in T.BAND_ORDER]
        peak = max(vals) if vals else 0.0
        if peak < 1e-9:
            self._targets = [0.0] * self.NUM_BARS
            return

        # Normalise against the loudest band, then resample the 6 bands up to
        # NUM_BARS with cosine interpolation for a continuous-looking curve.
        norm = [v / peak for v in vals]
        n = len(norm)
        for i in range(self.NUM_BARS):
            pos = i / (self.NUM_BARS - 1) * (n - 1)
            lo = int(math.floor(pos))
            hi = min(lo + 1, n - 1)
            frac = pos - lo
            smooth = (1 - math.cos(frac * math.pi)) / 2
            self._targets[i] = _lerp(norm[lo], norm[hi], smooth)

    def set_classification(self, label: str, sublabel: str, confidence: float):
        self._label = label
        self._sublabel = sublabel
        self._confidence = confidence

    def on_tick(self, dt: float):
        self._phase += dt * 0.6
        # Fast attack, slow release -- standard meter ballistics, makes
        # transients visible without the field looking jittery.
        for i in range(self.NUM_BARS):
            tgt = self._targets[i]
            cur = self._values[i]
            rate = 0.35 if tgt > cur else 0.12
            self._values[i] = _lerp(cur, tgt, rate)

            if self._values[i] >= self._peaks[i]:
                self._peaks[i] = self._values[i]
                self._peak_hold[i] = 0.0
            else:
                self._peak_hold[i] += dt
                if self._peak_hold[i] > 0.5:
                    self._peaks[i] = max(0.0, self._peaks[i] - dt * 0.6)
        self.update()

    def _bar_color(self, t: float) -> QColor:
        """Blend across the band ramp by normalised x position."""
        stops = [T.BAND_COLORS[k] for k in T.BAND_ORDER]
        pos = t * (len(stops) - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, len(stops) - 1)
        f = pos - lo
        a, b = stops[lo], stops[hi]
        return QColor(
            int(_lerp(a.red(), b.red(), f)),
            int(_lerp(a.green(), b.green(), f)),
            int(_lerp(a.blue(), b.blue(), f)),
        )

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_surface(p)

        w, h = self.width(), self.height()
        pad = 20
        text_block = 96
        field = QRectF(pad, pad, w - pad * 2, h - pad * 2 - text_block)
        mid = field.center().y()
        half = field.height() / 2

        # Ambient glow behind the field, tinted by overall level.
        level = sum(self._values) / max(1, len(self._values))
        if level > 0.01:
            g = QRadialGradient(field.center(), field.width() * 0.55)
            glow = T.ACCENT
            g.setColorAt(0.0, QColor(glow.red(), glow.green(), glow.blue(), int(38 * level)))
            g.setColorAt(1.0, QColor(glow.red(), glow.green(), glow.blue(), 0))
            p.fillRect(field, QBrush(g))

        bar_w = field.width() / self.NUM_BARS
        gap = max(1.0, bar_w * 0.28)
        draw_w = bar_w - gap

        for i, v in enumerate(self._values):
            x = field.left() + i * bar_w + gap / 2
            t = i / (self.NUM_BARS - 1)
            col = self._bar_color(t)

            # Idle shimmer so the panel isn't dead flat during silence.
            amp = v
            if self._silent:
                amp = 0.02 + 0.012 * math.sin(self._phase * 2 + i * 0.35)

            bar_h = max(1.5, amp * half * 0.94)

            grad = QLinearGradient(0, mid - bar_h, 0, mid + bar_h)
            grad.setColorAt(0.0, QColor(col.red(), col.green(), col.blue(), 235))
            grad.setColorAt(0.5, QColor(col.red(), col.green(), col.blue(), 150))
            grad.setColorAt(1.0, QColor(col.red(), col.green(), col.blue(), 235))

            rect = QRectF(x, mid - bar_h, draw_w, bar_h * 2)
            path = QPainterPath()
            path.addRoundedRect(rect, draw_w / 2, draw_w / 2)
            p.fillPath(path, QBrush(grad))

            # Peak ticks -- only once the peak is clearly above the current bar,
            # otherwise they read as detached specks riding on top of it.
            pk = self._peaks[i]
            if not self._silent and pk - amp > 0.09:
                pk_h = pk * half * 0.94
                tick = QColor(col.red(), col.green(), col.blue(), 110)
                p.fillRect(QRectF(x, mid - pk_h - 1.2, draw_w, 1.2), tick)
                p.fillRect(QRectF(x, mid + pk_h, draw_w, 1.2), tick)

        # Centre line
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.drawLine(QPointF(field.left(), mid), QPointF(field.right(), mid))

        # ── Classification readout ──
        y = field.bottom() + 22
        p.setFont(T.display_font(19, QFont.Weight.DemiBold))
        p.setPen(QPen(T.TEXT_PRIMARY))
        p.drawText(QRectF(pad, y, w - pad * 2, 28), Qt.AlignHCenter | Qt.AlignVCenter, self._label)

        p.setFont(T.ui_font(9.5))
        p.setPen(QPen(T.TEXT_TERTIARY))
        p.drawText(QRectF(pad, y + 28, w - pad * 2, 20),
                   Qt.AlignHCenter | Qt.AlignVCenter, self._sublabel)

        # Confidence bar
        if self._confidence > 0:
            bw = 180
            bx = (w - bw) / 2
            by = y + 54
            p.fillRect(QRectF(bx, by, bw, 3), QColor(255, 255, 255, 26))
            p.fillRect(QRectF(bx, by, bw * min(1.0, self._confidence), 3), T.ACCENT)


class EqCurveWidget(Card):
    """Renders the actual composite EQ transfer curve currently written to
    Equalizer APO -- target curve + preset + dynamic rider, summed.

    This is computed from the same filter tuples the backend writes, so what
    you see is what's applied, not a decorative approximation.
    """

    def __init__(self, parent=None):
        super().__init__("Response Curve", "Target + Preset + Dynamic", parent)
        self.setMinimumHeight(176)

        self._target_filters = []
        self._filters = []
        self._blend = 1.0
        self._bypassed = False

    def set_bypassed(self, value: bool):
        if value != self._bypassed:
            self._bypassed = value
            self.set_subtitle("Not applied — bypassed" if value else "Target + Preset + Dynamic")

    def set_filters(self, filters):
        """filters: list of (freq_hz, gain_db, q)"""
        new = list(filters or [])
        if new != self._target_filters:
            self._filters = self._sample(self._target_filters) if self._target_filters else None
            self._target_filters = new
            self._blend = 0.0

    def on_tick(self, dt: float):
        if self._blend < 1.0:
            self._blend = min(1.0, self._blend + dt * 3.0)
            self.update()

    @staticmethod
    def _peaking_db(f: float, fc: float, gain: float, q: float) -> float:
        """Magnitude response of an RBJ peaking EQ at frequency f, in dB.

        Uses the analog prototype, which is accurate enough for display and
        avoids needing the sample rate.
        """
        if fc <= 0 or f <= 0:
            return 0.0
        w = f / fc
        # |H| for an analog peaking filter: gain applied within a band of width fc/Q
        denom = (w - 1.0 / w) * q
        return gain / (1.0 + denom * denom)

    def _sample(self, filters, n: int = 220):
        """Sample the summed response across 20Hz..20kHz (log spaced)."""
        pts = []
        for i in range(n):
            t = i / (n - 1)
            f = 20.0 * ((20000.0 / 20.0) ** t)
            total = 0.0
            for (fc, gain, q) in filters:
                total += self._peaking_db(f, float(fc), float(gain), float(q))
            pts.append(total)
        return pts

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_surface(p)

        pad_l, pad_r = 38, 14
        pad_t = self.header_height() + 6
        pad_b = 24
        plot = QRectF(pad_l, pad_t, self.width() - pad_l - pad_r,
                      self.height() - pad_t - pad_b)
        if plot.width() <= 10 or plot.height() <= 10:
            return

        # Recessed well
        well = QPainterPath()
        well.addRoundedRect(plot.adjusted(-8, -6, 8, 6), T.RADIUS_INSET, T.RADIUS_INSET)
        p.fillPath(well, QBrush(T.SURFACE_INSET))

        DB_RANGE = 12.0

        def y_for(db):
            return plot.center().y() - (db / DB_RANGE) * (plot.height() / 2)

        def x_for(freq):
            t = math.log10(freq / 20.0) / math.log10(20000.0 / 20.0)
            return plot.left() + t * plot.width()

        # Grid: dB lines
        p.setFont(T.mono_font(7.5))
        for db in (-12, -6, 0, 6, 12):
            yy = y_for(db)
            is_zero = db == 0
            p.setPen(QPen(QColor(255, 255, 255, 34 if is_zero else 16), 1))
            p.drawLine(QPointF(plot.left(), yy), QPointF(plot.right(), yy))
            p.setPen(QPen(T.TEXT_DISABLED))
            p.drawText(QRectF(0, yy - 8, pad_l - 8, 16),
                       Qt.AlignRight | Qt.AlignVCenter, f"{db:+d}")

        # Grid: frequency decades
        for freq, lbl in ((100, "100"), (1000, "1k"), (10000, "10k")):
            xx = x_for(freq)
            p.setPen(QPen(QColor(255, 255, 255, 16), 1))
            p.drawLine(QPointF(xx, plot.top()), QPointF(xx, plot.bottom()))
            p.setPen(QPen(T.TEXT_DISABLED))
            p.drawText(QRectF(xx - 20, plot.bottom() + 4, 40, 14),
                       Qt.AlignHCenter | Qt.AlignTop, lbl)

        if not self._target_filters:
            p.setFont(T.ui_font(9))
            p.setPen(QPen(T.TEXT_DISABLED))
            p.drawText(plot, Qt.AlignCenter, "No filters applied")
            return

        target = self._sample(self._target_filters)
        if self._filters and len(self._filters) == len(target) and self._blend < 1.0:
            # Ease-out blend between the previous and new curve so preset
            # switches glide instead of snapping.
            e = 1 - (1 - self._blend) ** 3
            curve = [_lerp(a, b, e) for a, b in zip(self._filters, target)]
        else:
            curve = target

        n = len(curve)
        pts = [QPointF(plot.left() + (i / (n - 1)) * plot.width(),
                       max(plot.top(), min(plot.bottom(), y_for(curve[i]))))
               for i in range(n)]

        # Filled area under/over the 0dB line
        zero_y = y_for(0)
        fill = QPainterPath()
        fill.moveTo(pts[0].x(), zero_y)
        for pt in pts:
            fill.lineTo(pt)
        fill.lineTo(pts[-1].x(), zero_y)
        fill.closeSubpath()

        # Dim to a neutral grey while bypassed -- this curve isn't reaching
        # the audio right now, and color is the fastest way to say so.
        line_col = T.TEXT_DISABLED if self._bypassed else T.ACCENT
        fade = 0.4 if self._bypassed else 1.0

        grad = QLinearGradient(0, plot.top(), 0, plot.bottom())
        grad.setColorAt(0.0, QColor(line_col.red(), line_col.green(), line_col.blue(), int(90 * fade)))
        grad.setColorAt(0.5, QColor(line_col.red(), line_col.green(), line_col.blue(), int(18 * fade)))
        grad.setColorAt(1.0, QColor(line_col.red(), line_col.green(), line_col.blue(), int(90 * fade)))
        p.fillPath(fill, QBrush(grad))

        # The curve itself
        line = QPainterPath()
        line.moveTo(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        pen_col = QColor(line_col)
        if self._bypassed:
            pen_col.setAlphaF(0.7)
        p.setPen(QPen(pen_col, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(line)

        # Filter node markers. Placed on the *summed* curve at each filter's
        # centre frequency -- plotting them at the filter's own gain would
        # float them off the line wherever neighbouring filters overlap.
        for (fc, gain, q) in self._target_filters:
            fcf = float(fc)
            if fcf < 20 or fcf > 20000:
                continue
            summed = sum(self._peaking_db(fcf, float(f2), float(g2), float(q2))
                         for (f2, g2, q2) in self._target_filters)
            cx, cy = x_for(fcf), y_for(summed)
            if cy < plot.top() - 4 or cy > plot.bottom() + 4:
                continue
            p.setBrush(QBrush(QColor(20, 20, 24, 220)))
            p.setPen(QPen(line_col, 1.5))
            p.drawEllipse(QPointF(cx, cy), 3.0, 3.0)


class GainRiderWidget(Card):
    """Per-band dynamic gain adjustments as bipolar meters around a 0dB axis.

    Bars grow up for boost and down for cut, which makes the rider's
    behaviour legible at a glance -- you can see it clamping a hot band.
    """

    MAX_DB = 3.0

    def __init__(self, parent=None):
        super().__init__("Dynamic Gain Rider", "±3.0 dB", parent)
        self.setMinimumHeight(132)
        self._targets = {k: 0.0 for k in T.BAND_ORDER}
        self._values = {k: 0.0 for k in T.BAND_ORDER}

    def set_adjustments(self, adj: dict):
        for k in T.BAND_ORDER:
            self._targets[k] = float(adj.get(k, 0.0))

    def on_tick(self, dt: float):
        changed = False
        for k in T.BAND_ORDER:
            if abs(self._values[k] - self._targets[k]) > 0.001:
                self._values[k] = _lerp(self._values[k], self._targets[k], 0.18)
                changed = True
        if changed:
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_surface(p)

        pad = 16
        top = self.header_height() + 4
        area = QRectF(pad, top, self.width() - pad * 2, self.height() - top - pad)
        if area.height() < 40:
            return

        label_h = 16
        track = QRectF(area.left(), area.top(), area.width(), area.height() - label_h)
        mid = track.center().y()
        half = track.height() / 2 - 4

        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.drawLine(QPointF(track.left(), mid), QPointF(track.right(), mid))

        n = len(T.BAND_ORDER)
        col_w = track.width() / n
        bar_w = min(26.0, col_w * 0.42)

        for i, k in enumerate(T.BAND_ORDER):
            cx = track.left() + col_w * (i + 0.5)
            v = self._values[k]
            frac = max(-1.0, min(1.0, v / self.MAX_DB))
            bh = abs(frac) * half

            col = T.POSITIVE if v >= 0 else T.NEGATIVE

            # Track well -- kept faint so the meters read as bars against the
            # card, not as a row of dark slabs.
            wp = QPainterPath()
            wp.addRoundedRect(QRectF(cx - bar_w / 2, track.top() + 2, bar_w, track.height() - 4), 3, 3)
            p.fillPath(wp, QBrush(QColor(0, 0, 0, 28)))

            if bh > 0.6:
                rect = (QRectF(cx - bar_w / 2, mid - bh, bar_w, bh) if v >= 0
                        else QRectF(cx - bar_w / 2, mid, bar_w, bh))
                bp = QPainterPath()
                bp.addRoundedRect(rect, 3, 3)
                grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                grad.setColorAt(0.0, QColor(col.red(), col.green(), col.blue(), 230))
                grad.setColorAt(1.0, QColor(col.red(), col.green(), col.blue(), 120))
                p.fillPath(bp, QBrush(grad))

            # dB readout
            p.setFont(T.mono_font(7.5))
            p.setPen(QPen(T.TEXT_SECONDARY if abs(v) > 0.15 else T.TEXT_DISABLED))
            p.drawText(QRectF(cx - col_w / 2, track.top() - 2, col_w, 14),
                       Qt.AlignHCenter | Qt.AlignTop, f"{v:+.1f}")

            # Band label
            p.setFont(T.ui_font(7.5, QFont.Weight.DemiBold))
            p.setPen(QPen(T.TEXT_TERTIARY))
            p.drawText(QRectF(cx - col_w / 2, track.bottom() + 2, col_w, label_h),
                       Qt.AlignHCenter | Qt.AlignVCenter, T.BAND_LABELS[k])


class ClassifierWidget(Card):
    """Top-N YAMNet predictions as horizontal confidence bars."""

    ROWS = 5

    def __init__(self, parent=None):
        super().__init__("Neural Classifier", "YAMNet", parent)
        self.setMinimumHeight(176)
        self._preds = []
        self._shown = [0.0] * self.ROWS

    def set_predictions(self, preds):
        self._preds = list(preds or [])[: self.ROWS]

    def on_tick(self, dt: float):
        changed = False
        for i in range(self.ROWS):
            tgt = self._preds[i]["confidence"] if i < len(self._preds) else 0.0
            if abs(self._shown[i] - tgt) > 0.002:
                self._shown[i] = _lerp(self._shown[i], tgt, 0.2)
                changed = True
        if changed:
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_surface(p)

        pad = 16
        top = self.header_height()
        avail = self.height() - top - pad
        if avail < 40:
            return

        if not self._preds:
            p.setFont(T.ui_font(9))
            p.setPen(QPen(T.TEXT_DISABLED))
            p.drawText(QRectF(pad, top, self.width() - pad * 2, avail),
                       Qt.AlignCenter, "Listening…")
            return

        row_h = avail / self.ROWS
        name_w = 128
        pct_w = 42

        for i in range(self.ROWS):
            y = top + i * row_h
            conf = self._shown[i]
            name = self._preds[i]["class_name"] if i < len(self._preds) else ""
            if not name:
                continue

            p.setFont(T.ui_font(9 if i == 0 else 8.5,
                                QFont.Weight.DemiBold if i == 0 else QFont.Weight.Normal))
            p.setPen(QPen(T.TEXT_PRIMARY if i == 0 else T.TEXT_SECONDARY))
            fm = QFontMetricsF(p.font())
            elided = fm.elidedText(name, Qt.ElideRight, name_w)
            p.drawText(QRectF(pad, y, name_w, row_h), Qt.AlignLeft | Qt.AlignVCenter, elided)

            bar_x = pad + name_w + 8
            bar_w = self.width() - bar_x - pad - pct_w
            bar_y = y + row_h / 2 - 3

            if bar_w > 10:
                bg = QPainterPath()
                bg.addRoundedRect(QRectF(bar_x, bar_y, bar_w, 6), 3, 3)
                p.fillPath(bg, QBrush(QColor(255, 255, 255, 20)))

                fw = max(0.0, min(1.0, conf)) * bar_w
                if fw > 1:
                    fp = QPainterPath()
                    fp.addRoundedRect(QRectF(bar_x, bar_y, fw, 6), 3, 3)
                    grad = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
                    if i == 0:
                        grad.setColorAt(0.0, T.ACCENT)
                        grad.setColorAt(1.0, QColor(0x7C, 0x6B, 0xFF))
                    else:
                        c = QColor(255, 255, 255, 110)
                        grad.setColorAt(0.0, c)
                        grad.setColorAt(1.0, c)
                    p.fillPath(fp, QBrush(grad))

            p.setFont(T.mono_font(8))
            p.setPen(QPen(T.TEXT_TERTIARY))
            p.drawText(QRectF(self.width() - pad - pct_w, y, pct_w, row_h),
                       Qt.AlignRight | Qt.AlignVCenter, f"{conf * 100:.0f}%")


class PresetBar(QWidget):
    """Segmented preset selector. 'Auto' plus one segment per preset, with a
    sliding Fluent selection pill."""

    selected = Signal(str)

    def __init__(self, presets: dict, parent=None):
        super().__init__(parent)
        self.setFixedHeight(46)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

        self._items = [("auto", "Auto", "AI")]
        for pid, meta in presets.items():
            self._items.append((pid, meta.get("name", pid), meta.get("icon", "")))

        self._active = 0
        self._hover = -1
        self._pill_x = 0.0
        self._pill_target = 0.0
        self._auto_resolved = None

    def set_active(self, preset_id: str):
        for i, (pid, _, _) in enumerate(self._items):
            if pid == preset_id:
                if self._active != i:
                    self._active = i
                    self.update()
                return

    def set_auto_resolved(self, preset_id):
        """When in Auto, show which preset the engine actually landed on."""
        if self._auto_resolved != preset_id:
            self._auto_resolved = preset_id
            self.update()

    def _seg_w(self) -> float:
        return self.width() / max(1, len(self._items))

    def on_tick(self, dt: float):
        self._pill_target = self._active * self._seg_w()
        if abs(self._pill_x - self._pill_target) > 0.4:
            self._pill_x = _lerp(self._pill_x, self._pill_target, 0.25)
            self.update()
        else:
            self._pill_x = self._pill_target

    def mouseMoveEvent(self, e):
        idx = int(e.position().x() // max(1.0, self._seg_w()))
        idx = max(0, min(len(self._items) - 1, idx))
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, _):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        idx = int(e.position().x() // max(1.0, self._seg_w()))
        idx = max(0, min(len(self._items) - 1, idx))
        if idx != self._active:
            self._active = idx
            self.selected.emit(self._items[idx][0])
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, T.RADIUS_CONTROL, T.RADIUS_CONTROL)
        p.fillPath(path, QBrush(T.SURFACE_CONTROL))
        p.setPen(QPen(T.STROKE_CONTROL, 1))
        p.drawPath(path)

        seg = self._seg_w()

        # Hover wash
        if self._hover >= 0 and self._hover != self._active:
            hp = QPainterPath()
            hp.addRoundedRect(QRectF(self._hover * seg + 3, 3, seg - 6, self.height() - 6),
                              T.RADIUS_CONTROL - 2, T.RADIUS_CONTROL - 2)
            p.fillPath(hp, QBrush(QColor(255, 255, 255, 14)))

        # Selection pill
        pill = QRectF(self._pill_x + 3, 3, seg - 6, self.height() - 6)
        pp = QPainterPath()
        pp.addRoundedRect(pill, T.RADIUS_CONTROL - 2, T.RADIUS_CONTROL - 2)
        p.fillPath(pp, QBrush(QColor(255, 255, 255, 30)))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawPath(pp)

        # Fluent accent underline on the active segment
        p.fillRect(QRectF(pill.center().x() - 9, pill.bottom() - 3, 18, 2.5), T.ACCENT)

        for i, (pid, name, icon) in enumerate(self._items):
            x = i * seg
            active = i == self._active
            p.setFont(T.ui_font(9, QFont.Weight.DemiBold if active else QFont.Weight.Normal))
            p.setPen(QPen(T.TEXT_PRIMARY if active else T.TEXT_TERTIARY))

            text = name
            if pid == "auto" and self._auto_resolved and active:
                text = f"Auto · {self._auto_resolved}"

            fm = QFontMetricsF(p.font())
            p.drawText(QRectF(x, 0, seg, self.height()), Qt.AlignCenter,
                       fm.elidedText(text, Qt.ElideRight, seg - 12))


class BypassToggle(QWidget):
    """A/B comparison switch: 'EQ ON' vs 'BYPASS', styled as a Fluent segmented
    toggle so flipping it reads as a deliberate audio state change, not a
    settings checkbox buried in a menu."""

    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(148, 40)
        self.setCursor(Qt.PointingHandCursor)
        self._bypassed = False
        self._knob_x = 2.0
        self._knob_target = 2.0

    def is_bypassed(self) -> bool:
        return self._bypassed

    def set_bypassed(self, value: bool, animate: bool = True):
        if value == self._bypassed:
            return
        self._bypassed = value
        self._knob_target = (self.width() / 2) if value else 2.0
        if not animate:
            self._knob_x = self._knob_target
        self.update()

    def on_tick(self, dt: float):
        if abs(self._knob_x - self._knob_target) > 0.4:
            self._knob_x = _lerp(self._knob_x, self._knob_target, 0.3)
            self.update()
        else:
            self._knob_x = self._knob_target

    def mousePressEvent(self, e):
        self._bypassed = not self._bypassed
        self._knob_target = (self.width() / 2) if self._bypassed else 2.0
        self.toggled.emit(self._bypassed)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, T.RADIUS_CONTROL, T.RADIUS_CONTROL)
        base = QColor(T.CRITICAL) if self._bypassed else QColor(T.SURFACE_CONTROL)
        if self._bypassed:
            base.setAlpha(28)
        p.fillPath(path, QBrush(base))
        stroke = T.CRITICAL if self._bypassed else T.STROKE_CONTROL
        p.setPen(QPen(stroke, 1))
        p.drawPath(path)

        half_w = self.width() / 2 - 4
        knob = QRectF(self._knob_x, 2, half_w, self.height() - 4)
        kp = QPainterPath()
        kp.addRoundedRect(knob, T.RADIUS_CONTROL - 2, T.RADIUS_CONTROL - 2)
        knob_col = T.CRITICAL if self._bypassed else T.POSITIVE
        fill = QColor(knob_col)
        fill.setAlpha(46)
        p.fillPath(kp, QBrush(fill))
        p.setPen(QPen(knob_col, 1))
        p.drawPath(kp)

        p.setFont(T.ui_font(8, QFont.Weight.DemiBold))
        left_col = T.POSITIVE if not self._bypassed else T.TEXT_DISABLED
        right_col = T.CRITICAL if self._bypassed else T.TEXT_DISABLED
        p.setPen(QPen(left_col))
        p.drawText(QRectF(0, 0, self.width() / 2, self.height()), Qt.AlignCenter, "EQ ON")
        p.setPen(QPen(right_col))
        p.drawText(QRectF(self.width() / 2, 0, self.width() / 2, self.height()), Qt.AlignCenter, "BYPASS")


class StatusStrip(QWidget):
    """Compact key/value telemetry row along the bottom of the window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        self._items = []

    def set_items(self, items):
        """items: list of (label, value, QColor|None)"""
        if items != self._items:
            self._items = items
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._items:
            return

        n = len(self._items)
        seg = self.width() / n
        for i, (label, value, color) in enumerate(self._items):
            x = i * seg
            p.setFont(T.ui_font(7.5, QFont.Weight.DemiBold))
            p.setPen(QPen(T.TEXT_DISABLED))
            p.drawText(QRectF(x + 12, 4, seg - 24, 14), Qt.AlignLeft | Qt.AlignVCenter,
                       label.upper())

            p.setFont(T.ui_font(9))
            p.setPen(QPen(color or T.TEXT_SECONDARY))
            fm = QFontMetricsF(p.font())
            p.drawText(QRectF(x + 12, 18, seg - 24, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(value, Qt.ElideRight, seg - 24))

            if i < n - 1:
                p.setPen(QPen(T.STROKE_DIVIDER, 1))
                p.drawLine(QPointF(x + seg, 8), QPointF(x + seg, self.height() - 8))
