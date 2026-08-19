"""
Program-dependent ("dynamic") EQ.

HONESTY NOTE ON WHAT THIS ACTUALLY IS:
True per-sample multiband compression needs a real-time DSP engine
processing every sample. We're steering Equalizer APO via periodic
config rewrites instead, so this is an *approximation* -- gain riding
at analysis-cycle granularity (every ~2s, see DYNAMIC_REFRESH_SECONDS
in main.py), not sample-accurate. That's enough to stop a boosted band
from staying overblown when a track gets unusually loud in that range,
and to lift a boosted band back up when it's under-represented -- but
it will not react within a single transient the way a real compressor
does. True sample-accurate dynamic EQ would mean writing a custom
real-time audio processing chain (e.g. a C++ APO plugin or a
WASAPI-exclusive processing loop), which is a much bigger project than
this.
"""

import numpy as np

# Representative frequency for placing each band's corrective filter.
BAND_CENTER_HZ = {
    "sub_bass": 40,
    "bass": 120,
    "low_mid": 350,
    "mid": 1000,
    "high_mid": 3000,
    "treble": 8000,
}


class DynamicGainRider:
    """Tracks a slow rolling baseline per band and computes a small
    corrective gain (in dB) that pulls back a band when it's currently
    hotter than its own recent average, and lifts it when it's quieter
    -- independent of which content-adaptive preset is active."""

    def __init__(self, alpha: float = 0.02, max_adjust_db: float = 3.0):
        self.alpha = alpha  # much slower than analyzer.SmoothedFeatures -- this is the long-term baseline
        self.max_adjust_db = max_adjust_db
        self.baseline = None

    def update(self, energies: dict) -> dict:
        if self.baseline is None:
            self.baseline = dict(energies)
            return {band: 0.0 for band in energies}

        adjustments = {}
        for band, value in energies.items():
            baseline = self.baseline[band]
            self.baseline[band] = self.alpha * value + (1 - self.alpha) * baseline

            if baseline < 1e-6:
                adjustments[band] = 0.0
                continue

            ratio = value / baseline  # >1 = currently hotter than its own baseline
            db = -10 * np.log10(max(ratio, 1e-6))
            adjustments[band] = float(np.clip(db, -self.max_adjust_db, self.max_adjust_db))
        return adjustments


def dynamic_filters(adjustments: dict) -> list:
    """Converts per-band dB adjustments into parametric filter tuples
    for merging with the target curve + preset filters."""
    filters = []
    for band, gain_db in adjustments.items():
        if abs(gain_db) < 0.3:  # skip negligible corrections -- not worth a config rewrite
            continue
        filters.append((BAND_CENTER_HZ[band], round(gain_db, 1), 1.0))
    return filters
