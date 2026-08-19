"""
Preset EQ curves (parametric filters: freq_hz, gain_db, Q) and the logic
that picks one based on smoothed band energies.

This is the piece to swap out later for an ML genre/mood classifier --
everything else in the pipeline (capture, analysis, applying to
Equalizer APO) stays the same either way.

NOTE: the thresholds in choose_preset() are starting points, not tuned
values. You will want to print the smoothed energies for a few tracks
you know well and adjust these against what you actually hear.
"""

PRESETS = {
    "bass_boost": {
        "name": "Bass Boost",
        "description": "Thumping low-end for electronic and hip-hop",
        "icon": "🎧",
        "color": "#8b5cf6",
        "filters": [
            (60, 5.0, 0.8),
            (150, 2.5, 1.0),
            (8000, -1.0, 0.7),
        ]
    },
    "vocal_mid": {
        "name": "Vocal Clarity",
        "description": "Pushes vocals and speech to the front",
        "icon": "🎙️",
        "color": "#3b82f6",
        "filters": [
            (100, -1.5, 0.8),
            (1000, 3.0, 1.0),
            (3000, 2.0, 1.2),
        ]
    },
    "treble_smooth": {
        "name": "Acoustic Smooth",
        "description": "Tames harsh highs, warms the sound",
        "icon": "🎻",
        "color": "#10b981",
        "filters": [
            (60, 1.0, 0.8),
            (6000, -2.5, 1.0),
            (10000, -3.0, 0.9),
        ]
    },
    "v_shape": {
        "name": "High Energy",
        "description": "V-shaped EQ for rock and high-energy tracks",
        "icon": "⚡",
        "color": "#ef4444",
        "filters": [
            (80, 4.0, 0.9),
            (1000, -1.5, 1.0),
            (8000, 3.0, 0.9),
        ]
    },
    "balanced": {
        "name": "Balanced Reference",
        "description": "Subtle tweaks for a clean, neutral sound",
        "icon": "⚖️",
        "color": "#94a3b8",
        "filters": [
            (100, 1.0, 0.8),
            (1000, 0.5, 1.0),
            (6000, 1.0, 1.0),
        ]
    },
}
