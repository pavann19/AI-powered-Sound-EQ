"""
The app's icon artwork, factored out of app_native.py so it can be rendered
without booting the full GUI -- generate_icon.py uses this to bake a real
.ico file for Desktop/Start Menu/taskbar shortcuts, which need a static icon
file rather than the runtime-drawn QIcon the running app uses for its window
and tray icon.
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QPixmap, QPen, QBrush, QPainterPath, QLinearGradient

ACCENT = QColor(0x60, 0xCD, 0xFF)  # Win11 default dark accent -- kept in sync with ui_theme.ACCENT


def draw_app_icon(size: int = 64) -> QPixmap:
    """Accent-tinted waveform on a rounded square, matching the Win11 icon
    silhouette."""
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

    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(ACCENT))
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
    return pm
