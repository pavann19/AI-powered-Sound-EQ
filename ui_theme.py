"""
Windows 11 Fluent design tokens for the native SoundIntelligence UI.

Colors follow the Win11 dark-theme system palette so the app sits on a Mica
backdrop the way first-party Windows apps do, rather than imitating another
platform's material. Surfaces are deliberately semi-transparent -- Mica is
painted by the compositor *behind* the window, so opaque cards would hide it.
"""

from PySide6.QtGui import QColor, QFont, QFontDatabase

# ── Surfaces ────────────────────────────────────────────────────────────
# Alpha matters: these sit on top of the DWM Mica backdrop.
SURFACE_CARD = QColor(255, 255, 255, 10)       # "Layer" fill
SURFACE_CARD_HOVER = QColor(255, 255, 255, 16)
SURFACE_INSET = QColor(0, 0, 0, 70)            # recessed wells (graphs, meters)
SURFACE_CONTROL = QColor(255, 255, 255, 15)    # buttons / pills
SURFACE_CONTROL_HOVER = QColor(255, 255, 255, 26)
SURFACE_CONTROL_PRESS = QColor(255, 255, 255, 8)

# ── Strokes ─────────────────────────────────────────────────────────────
STROKE_CARD = QColor(255, 255, 255, 18)
STROKE_CONTROL = QColor(255, 255, 255, 24)
STROKE_DIVIDER = QColor(255, 255, 255, 14)

# ── Text (Win11 dark theme text ramp) ───────────────────────────────────
TEXT_PRIMARY = QColor(255, 255, 255, 255)
TEXT_SECONDARY = QColor(255, 255, 255, 200)
TEXT_TERTIARY = QColor(255, 255, 255, 140)
TEXT_DISABLED = QColor(255, 255, 255, 92)
TEXT_ON_ACCENT = QColor(0, 0, 0, 230)

# ── Accent (Win11 default dark accent) ──────────────────────────────────
ACCENT = QColor(0x60, 0xCD, 0xFF)              # #60CDFF
ACCENT_DIM = QColor(0x60, 0xCD, 0xFF, 60)
ACCENT_FAINT = QColor(0x60, 0xCD, 0xFF, 26)

# ── Spectral band ramp (low -> high frequency) ──────────────────────────
# Cool for lows through warm for highs, so the spectrum reads as a gradient
# rather than 6 arbitrary colors.
BAND_COLORS = {
    "sub_bass": QColor(0x7C, 0x6B, 0xFF),
    "bass":     QColor(0x60, 0xA5, 0xFF),
    "low_mid":  QColor(0x60, 0xCD, 0xFF),
    "mid":      QColor(0x5A, 0xE0, 0xC8),
    "high_mid": QColor(0xF5, 0xC9, 0x6B),
    "treble":   QColor(0xFF, 0x8F, 0x7A),
}

# Semantic
POSITIVE = QColor(0x6C, 0xCB, 0x5F)
NEGATIVE = QColor(0xFF, 0x99, 0x66)
CRITICAL = QColor(0xFF, 0x62, 0x5A)

BAND_ORDER = ["sub_bass", "bass", "low_mid", "mid", "high_mid", "treble"]
BAND_LABELS = {
    "sub_bass": "SUB",
    "bass": "BASS",
    "low_mid": "L-MID",
    "mid": "MID",
    "high_mid": "H-MID",
    "treble": "TREBLE",
}

# ── Metrics ─────────────────────────────────────────────────────────────
RADIUS_CARD = 8      # Win11 uses restrained radii, not big pill shapes
RADIUS_CONTROL = 6
RADIUS_INSET = 6


def _pick_family(*candidates: str) -> str:
    """Return the first font family actually present on this machine."""
    available = set(QFontDatabase.families())
    for name in candidates:
        if name in available:
            return name
    return candidates[-1]


def ui_font(size: float = 10.0, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Segoe UI Variable is the Win11 system face; fall back down the chain
    on older builds or if it's been removed."""
    family = _pick_family("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Arial")
    f = QFont(family, -1, weight)
    f.setPointSizeF(size)
    return f


def display_font(size: float = 16.0, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    """Segoe UI Variable Display is optically sized for large text."""
    family = _pick_family("Segoe UI Variable Display", "Segoe UI Variable", "Segoe UI", "Arial")
    f = QFont(family, -1, weight)
    f.setPointSizeF(size)
    return f


def mono_font(size: float = 9.0, weight: QFont.Weight = QFont.Weight.Medium) -> QFont:
    """Cascadia Mono ships with Win11 and matches the system aesthetic
    better than a webfont would."""
    family = _pick_family("Cascadia Mono", "Consolas", "Courier New")
    f = QFont(family, -1, weight)
    f.setPointSizeF(size)
    return f
