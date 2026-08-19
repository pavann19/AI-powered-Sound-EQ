"""
Baseline correction curve for the Sony WH-CH720N, layered underneath the
content-adaptive preset so the headset's own tuning quirks are corrected
first -- then content-adaptive EQ works from a more neutral starting
point instead of compounding on top of the hardware's existing bias.

SOURCE / HONESTY NOTE:
SoundGuys' measured review of the WH-CH720N
(soundguys.com/sony-wh-ch720n-review-99305) reports three directional
findings:
  - A boost in the ~100-400 Hz range (excess bass/warmth)
  - Reduced upper-midrange ~900 Hz-4 kHz (vocals/instruments recessed
    in busy mixes)
  - Exaggerated treble ~5-10 kHz

These are *directional* findings from a written review, not exact dB
figures read off a raw measurement graph. I don't have access to
Rtings' actual numeric FR deviation data (their charts are
JS-rendered, not present in fetched page text), so the gains below are
conservative, reasonable-sounding starting corrections -- not
lab-verified numbers. Treat this the way you'd treat an unverified
resume metric: flagged, not fabricated. Refine by ear, or -- if you
want this rigorous -- measure your actual unit with REW + a calibrated
measurement mic and replace these values with real deviation data.
"""

TARGET_CURVE_FILTERS = [
    # (freq_hz, gain_db, Q)
    (150, -3.0, 0.9),   # tame the reported ~100-400Hz bass excess
    (280, -1.5, 1.0),
    (2000, 2.0, 1.1),   # restore the reported recessed 900Hz-4kHz upper-mid
    (7000, -2.5, 1.0),  # tame the reported ~5-10kHz treble exaggeration
]
