"""
Windows 11 DWM backdrop integration.

Applies the real system Mica/Acrylic material to a Qt window via
DwmSetWindowAttribute, which is how first-party Windows apps get their
translucency -- the compositor samples and blurs the desktop wallpaper behind
the window. This is genuinely different from drawing a blurred bitmap
ourselves: it's GPU-composited by DWM, respects the user's transparency
accessibility setting, and updates as the wallpaper/theme changes.

Everything here degrades silently: on Windows 10, on builds without the
system-backdrop attribute, or if the calls fail, the app just renders on its
solid dark base color with no visual breakage.
"""

import ctypes
import sys
from ctypes import wintypes

# DwmSetWindowAttribute attribute ids
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38

# DWM_SYSTEMBACKDROP_TYPE
BACKDROP_AUTO = 0
BACKDROP_NONE = 1
BACKDROP_MICA = 2          # desktop wallpaper tint -- for long-lived app windows
BACKDROP_ACRYLIC = 3       # heavier blur -- for transient surfaces / flyouts
BACKDROP_MICA_ALT = 4      # "Tabbed" -- higher contrast Mica variant

# DWM_WINDOW_CORNER_PREFERENCE
CORNER_DEFAULT = 0
CORNER_DONOTROUND = 1
CORNER_ROUND = 2
CORNER_ROUNDSMALL = 3


def _win_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def supports_mica() -> bool:
    """DWMWA_SYSTEMBACKDROP_TYPE landed in Windows 11 22H2 (build 22621)."""
    return _win_build() >= 22621


def _set_attr(hwnd: int, attr: int, value: int) -> bool:
    try:
        dwm = ctypes.windll.dwmapi
        val = ctypes.c_int(value)
        res = dwm.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(attr),
            ctypes.byref(val),
            ctypes.sizeof(val),
        )
        return res == 0
    except Exception:
        return False


def apply_backdrop(window, backdrop: int = BACKDROP_MICA_ALT, dark: bool = True) -> bool:
    """Apply a DWM system backdrop to a Qt window.

    Returns True if the backdrop was applied -- callers use this to decide
    whether to paint an opaque fallback background instead.
    """
    if sys.platform != "win32":
        return False

    try:
        hwnd = int(window.winId())
    except Exception:
        return False

    # Dark mode first so the non-client area (title bar, border) matches
    # before the backdrop is composited behind it.
    if dark:
        _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)

    _set_attr(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, CORNER_ROUND)

    if not supports_mica():
        return False

    return _set_attr(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, backdrop)
