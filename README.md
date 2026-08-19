# SoundIntelligence — Adaptive EQ for Windows

Real-time EQ tuning driven by analyzing the audio actually playing (not which
app is playing it). Applies EQ system-wide via Equalizer APO before audio
reaches the headset, so the headset's own EQ can stay off.

Built for the Sony WH-CH720N, but the only headset-specific piece is
`target_curve.py` — swap that and it works for anything.

## Architecture

```
audio_capture ──► analyzer ──────┐
 (WASAPI          (6-band FFT)   │
  loopback)                      ├──► intelligence ──► preset choice
                 ml_analyzer ────┘    (fuses ML 70% / spectral 30%)
                 (YAMNet)                     │
                 fingerprint_cache ───────────┤ (instant recall of known tracks)
                                              ▼
              target_curve + preset + dynamic_eq ──► apo_writer ──► Equalizer APO
                                              │
                                              ▼
                                        app_native (Qt 6 UI)
```

The DSP pipeline runs on a background thread. `app_native.py` is purely the
presentation layer, bridged to that thread by a Qt signal so all widget
mutation happens on the GUI thread.

## Setup

1. **Install Equalizer APO**: https://sourceforge.net/projects/equalizerapo/
   During install, when it asks which device to install as, pick your
   **headset's output device**. Reboot if prompted.

2. **Confirm the config path** matches `apo_writer.py`'s `APO_CONFIG_PATH`.
   Default is `C:\Program Files\EqualizerAPO\config\config.txt`.

3. **Install dependencies**:
   ```
   pip install -r requirements.txt
   ```

4. **Run**:
   ```
   python app_native.py
   ```
   Or double-click `Launch_SoundIntelligence.bat` to start it silently in the
   tray with no console window.

First launch downloads YAMNet's `.tflite` model and class map (~16MB total)
into `.tflite_cache/`; subsequent launches load from disk and work offline.
Classification runs on the LiteRT (TFLite) interpreter rather than full
TensorFlow — same model, ~18MB dependency instead of ~600MB, and it loads in
well under a second instead of tens of seconds. See the docstring in
`ml_analyzer.py` for the measured numbers.

## The interface

Native Qt 6 (PySide6) window using the Windows 11 **Mica** system backdrop via
DWM — the compositor tints the window with your desktop wallpaper the same way
first-party Windows apps do. On Windows 10, or builds without
`DWMWA_SYSTEMBACKDROP_TYPE` (pre-22H2), it falls back to a solid dark surface
with no visual breakage.

- **Spectrum** — live 6-band energy resampled to 64 bars, cool-to-warm across
  the frequency range, with peak-hold ticks. Shows the top classification and
  its confidence underneath.
- **Neural Classifier** — YAMNet's top 5 predictions with confidences.
- **Response Curve** — the actual summed transfer function currently written to
  Equalizer APO (target curve + preset + dynamic rider), plotted log-frequency
  against dB. Node markers sit on the summed curve, not on each filter's own
  gain.
- **Dynamic Gain Rider** — per-band corrective gain as bipolar meters around
  0 dB. Green = boost, orange = cut.
- **Preset bar** — Auto (AI-chosen, shows what it resolved to) or force any
  preset manually.

Closing the window hides to tray; the DSP keeps running. Exit via the tray menu.

## Tuning (the part you'll actually spend time on)

- **`eq_presets.py`** — the preset curves (frequency, gain, Q). Starting
  guesses, not tuned values. Play tracks you know well, watch which preset the
  UI picks, and adjust.

- **`intelligence.py`** — `preset_keywords` maps YAMNet class names to presets,
  and the ML/spectral weighting (70/30) decides how much the classifier is
  trusted versus raw band energy.

- **`min_dwell_seconds`** in `main.py` (default 6.0) — how long before it will
  switch again. Lower = more responsive, higher = steadier.

- **`alpha`** in `SmoothedFeatures` (`analyzer.py`, default 0.15) — how fast the
  rolling average of the track's character updates.

- **`target_curve.py`** — the headset correction layered underneath everything.
  See the honesty note in that file: the values are directional corrections
  derived from a written review, not lab measurements.

## Known things to check on your machine

- `soundcard`'s loopback capture resolves the default speaker by name. If
  `get_loopback_mic()` fails, print `sc.all_microphones(include_loopback=True)`
  to see what's actually available.
- If Windows is set to a sample rate Equalizer APO wasn't configured for, match
  `SAMPLE_RATE` in `audio_capture.py` to the device's actual rate
  (Sound settings → device properties → advanced).
- Equalizer APO must be applied to whichever device Windows treats as default
  output. Switching outputs mid-session means the agent's writes won't affect
  audio until APO is configured for that device too.

## Legacy files

`server.py`, `tray_app.py`, and `static/` are the previous FastAPI + browser-
window UI, superseded by `app_native.py`. They're no longer wired into the
launchers and can be deleted.
