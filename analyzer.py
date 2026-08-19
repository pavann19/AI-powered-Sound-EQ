"""
Turns a raw audio block into normalized energy ratios per frequency band,
then smooths those ratios over time so the agent reacts to the character
of the track rather than to individual transients (kick drums, cymbal
hits, etc).
"""

import numpy as np

# Rough perceptual band boundaries in Hz. Tune these if a genre you
# care about isn't being categorized the way you'd expect.
BANDS = {
    "sub_bass": (20, 60),
    "bass": (60, 250),
    "low_mid": (250, 500),
    "mid": (500, 2000),      # vocals / melody live mostly here
    "high_mid": (2000, 4000),  # presence / clarity
    "treble": (4000, 16000),  # air / sparkle / sibilance
}


def band_energies(samples, sample_rate):
    """samples: numpy array [frames, channels] or [frames]. Returns a
    dict of band_name -> normalized energy (ratios sum to ~1.0)."""
    if samples.ndim > 1:
        samples = samples.mean(axis=1)  # downmix to mono

    n = len(samples)
    windowed = samples * np.hanning(n)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

    energies = {}
    for name, (lo, hi) in BANDS.items():
        mask = (freqs >= lo) & (freqs < hi)
        # Using sqrt to get amplitude-like scale rather than pure power, better for visualizer
        energies[name] = float(np.sqrt(np.sum(spectrum[mask] ** 2)))

    total = sum(energies.values()) + 1e-9
    ratios = {k: v / total for k, v in energies.items()}
    return {"raw": energies, "ratios": ratios}


class SmoothedFeatures:
    """Exponential moving average over band energies so the decision
    engine sees the 'settled' feel of a track, not frame-to-frame noise.

    alpha closer to 1.0 = reacts faster (but flappier).
    alpha closer to 0.0 = slower, steadier.
    """

    def __init__(self, alpha=0.15):
        self.alpha = alpha
        self.state = None

    def update(self, energies_dict):
        energies_ratios = energies_dict["ratios"]
        energies_raw = energies_dict["raw"]
        
        if self.state is None:
            self.state = {"ratios": dict(energies_ratios), "raw": dict(energies_raw)}
        else:
            for k, v in energies_ratios.items():
                self.state["ratios"][k] = self.alpha * v + (1 - self.alpha) * self.state["ratios"][k]
            for k, v in energies_raw.items():
                self.state["raw"][k] = self.alpha * v + (1 - self.alpha) * self.state["raw"][k]
        return self.state
