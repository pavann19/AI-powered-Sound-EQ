"""
One-time (or re-runnable) generator for SoundIntelligence.ico, baked from
the same artwork the running app draws for its window/tray icon
(app_icon.draw_app_icon). Desktop and Start Menu shortcuts need a static
.ico file on disk -- they can't point at a QIcon that only exists inside a
running process.

Run directly:
    python generate_icon.py
"""

import os
import sys

# Render offscreen -- this only needs to rasterize a few pixmaps, not open
# a window, so it shouldn't require (or flash) a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from app_icon import draw_app_icon

ICO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SoundIntelligence.ico")


def generate(path: str = ICO_PATH) -> bool:
    app = QApplication.instance() or QApplication(sys.argv)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    pixmaps = [draw_app_icon(s) for s in sizes]
    # Qt's ICO writer accepts multiple frames via QImage list through
    # QPixmap.save only for the largest; write each size as its own pass
    # isn't supported by a single save() call, so use the largest as the
    # canonical export -- Windows generates the smaller mip levels itself
    # from a single high-res source when displaying shortcuts/taskbar icons.
    ok = pixmaps[-1].save(path, "ICO")
    return ok and os.path.exists(path)


if __name__ == "__main__":
    ok = generate()
    print(f"Icon {'written to' if ok else 'FAILED to write to'} {ICO_PATH}")
    sys.exit(0 if ok else 1)
