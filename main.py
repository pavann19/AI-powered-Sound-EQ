import time
import threading
import numpy as np

from audio_capture import audio_stream, SAMPLE_RATE
from analyzer import band_energies, SmoothedFeatures
from ml_analyzer import YAMNetAnalyzer
from eq_presets import PRESETS
from intelligence import IntelligenceEngine
from preference_model import PreferenceModel
from apo_writer import write_filters

from target_curve import TARGET_CURVE_FILTERS
from dynamic_eq import DynamicGainRider, dynamic_filters

try:
    from fingerprint_cache import FingerprintCache
    fingerprint_cache = FingerprintCache()
except Exception as e:
    print(f"[fingerprint cache disabled: {e}]")
    fingerprint_cache = None

# Silence bands used when no audio is playing
_ZERO_BANDS = {"sub_bass":0, "bass":0, "low_mid":0, "mid":0, "high_mid":0, "treble":0}

class AudioProcessor:
    def __init__(self):
        self.ml_analyzer = YAMNetAnalyzer(sample_rate=SAMPLE_RATE)
        self.spectral_analyzer = SmoothedFeatures(alpha=0.15)
        self.intelligence = IntelligenceEngine()
        self.preference_model = PreferenceModel()
        self.rider = DynamicGainRider(alpha=0.02, max_adjust_db=3.0)

        self.current_preset = None
        self.last_switch_time = 0.0
        self.last_dynamic_update = 0.0
        self.min_dwell_seconds = 6.0
        self.manual_override = None  # If set to a preset ID, bypasses AI
        self.target_curve_active = True
        self._last_embedding = None   # most recent YAMNet embedding, for preference learning
        
        self.running = False
        self.thread = None
        self.callbacks = []    # functions to call with rich state
        self.history = []      # ring buffer of last 50 events
        self._last_broadcast = 0.0  # throttle broadcasts
        self._last_filters = None   # filters actually written to APO (interpolation baseline)
        self._computed_filters = []  # what the pipeline *would* apply, even while bypassed

        # A/B bypass: writes a flat (no-filter) config so you can instantly
        # compare "EQ on" vs "EQ off" on the same audio, instead of having to
        # trust that the processing is actually doing something.
        self.bypass = False
        self._bypass_lock = threading.Lock()

    def on_update(self, callback):
        self.callbacks.append(callback)
        
    def add_history_event(self, timestamp, ml_predictions, preset):
        event = {
            "timestamp": timestamp,
            "top_class": ml_predictions[0]["class_name"] if ml_predictions else "Unknown",
            "preset": preset
        }
        self.history.append(event)
        if len(self.history) > 50:
            self.history.pop(0)

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            
    def _apply_eq(self, preset_name, dynamic_adjustments):
        filters = []
        if self.target_curve_active:
            filters += list(TARGET_CURVE_FILTERS)
        if preset_name in PRESETS:
            filters += PRESETS[preset_name]["filters"]
        filters += dynamic_filters(dynamic_adjustments)
        self._computed_filters = filters

        with self._bypass_lock:
            if self.bypass:
                # Still track what *would* play so the UI curve stays live
                # and unbypassing snaps straight to the current decision
                # instead of a stale pre-bypass one.
                return
            write_filters(filters, old_filters=self._last_filters)
            self._last_filters = filters

    def set_bypass(self, on: bool):
        """Toggle A/B passthrough. Writes immediately rather than waiting for
        the next preset switch or dynamic-EQ refresh tick, so the comparison
        is instant. Safe to call from the GUI thread."""
        with self._bypass_lock:
            if on == self.bypass:
                return
            self.bypass = on
            target = [] if on else self._computed_filters
            write_filters(target, old_filters=self._last_filters)
            self._last_filters = target

    def set_manual_override(self, preset_id):
        """Setting an override is a ground-truth signal: "given what YAMNet
        just heard, this is the preset I actually wanted." Log it against the
        embedding from that moment before applying the override, so the
        preference model learns from real corrections instead of the
        pipeline's own guesses."""
        if preset_id and preset_id != self.manual_override and self._last_embedding is not None:
            self.preference_model.add_example(self._last_embedding, preset_id)
        self.manual_override = preset_id

    def _loop(self):
        print("AudioProcessor background thread started.")
        
        last_ml_predictions = []
        last_scores = {k: 0 for k in PRESETS.keys()}
        last_candidate = None
        current_fingerprint = None
        current_fingerprint_time = 0.0
        cached_preset = None
        FINGERPRINT_MAX_AGE = 8.0  # discard fingerprints older than this before remembering
        
        for chunk in audio_stream():
            if not self.running:
                break
            
            try:
                # audio_capture yields None for silence
                if chunk is None:
                    smoothed_raw = dict(_ZERO_BANDS)
                    dynamic_adjustments = dict(_ZERO_BANDS)
                    is_cached = False
                else:
                    # 1. Real-time Spectral Analysis
                    raw_energies = band_energies(chunk, SAMPLE_RATE)
                    smoothed_energies = self.spectral_analyzer.update(raw_energies)
                    smoothed_raw = smoothed_energies["raw"]
                    
                    # 2. Dynamic EQ (uses single band dictionary, e.g. smoothed_raw)
                    dynamic_adjustments = self.rider.update(smoothed_raw)
                    
                    now = time.time()

                    # 3. Fingerprint Cache
                    cached_preset = None
                    is_cached = False
                    if fingerprint_cache is not None:
                        fp = fingerprint_cache.feed(chunk)
                        if fp is not None:
                            current_fingerprint = fp
                            current_fingerprint_time = now
                            cached_preset = fingerprint_cache.lookup(fp)
                            if cached_preset:
                                is_cached = True

                    # 4. ML Analysis (buffered)
                    ml_result = self.ml_analyzer.process_chunk(chunk)

                    # If we get a new ML result, update our cached intelligence
                    if ml_result:
                        last_ml_predictions = ml_result["predictions"]
                        self._last_embedding = ml_result.get("embedding")

                        decision = self.intelligence.evaluate(
                            last_ml_predictions,
                            smoothed_energies["ratios"],
                            embedding=self._last_embedding,
                            preference_model=self.preference_model,
                        )

                        last_scores = decision["scores"]
                        last_candidate = decision["best_preset"]
                        
                    target_preset = self.manual_override if self.manual_override else (cached_preset or last_candidate)
                    
                    # Preset Switching Logic
                    switched = False
                    if target_preset and target_preset != self.current_preset and (now - self.last_switch_time) > self.min_dwell_seconds:
                        self._apply_eq(target_preset, dynamic_adjustments)
                        self.current_preset = target_preset
                        self.last_switch_time = now
                        self.last_dynamic_update = now
                        self.add_history_event(now, last_ml_predictions, target_preset)
                        switched = True
                        
                        if (fingerprint_cache is not None and current_fingerprint and not cached_preset
                                and (now - current_fingerprint_time) <= FINGERPRINT_MAX_AGE):
                            fingerprint_cache.remember(current_fingerprint, target_preset)
                        # Always clear after a switch decision so a stale fingerprint can't get
                        # attributed to a later, unrelated switch.
                        current_fingerprint = None
                    
                    # Dynamic EQ Refresh (every 1s)
                    if not switched and self.current_preset and (now - self.last_dynamic_update) > 1.0:
                        self._apply_eq(self.current_preset, dynamic_adjustments)
                        self.last_dynamic_update = now
            except Exception as e:
                print(f"[AudioProcessor Loop Error] {e}")
                continue

            # Throttle broadcasts to ~5/sec to avoid flooding subscribers
            now = time.time()
            if now - self._last_broadcast < 0.2:
                continue
            self._last_broadcast = now

            state = {
                "spectral": smoothed_raw,
                "silent": chunk is None,
                "ml_predictions": last_ml_predictions,
                "scores": last_scores,
                "candidate": self.manual_override if self.manual_override else (cached_preset or last_candidate),
                "current_preset": self.current_preset or last_candidate,
                "history": self.history,
                "dynamic_adjustments": dynamic_adjustments,
                "target_curve_active": self.target_curve_active,
                "is_cached": is_cached,
                "fingerprint_available": fingerprint_cache is not None,
                # The filter set the pipeline currently computes -- shown even
                # while bypassed, so the UI curve reflects the live decision
                # rather than going blank.
                "filters": list(self._computed_filters) if self._computed_filters else [],
                "bypass": self.bypass,
                "preference_ready": self.preference_model.ready,
                "preference_samples": self.preference_model.sample_count,
            }
            
            for cb in self.callbacks:
                try:
                    cb(state)
                except Exception as e:
                    print(f"[Callback Error] {e}")

if __name__ == "__main__":
    processor = AudioProcessor()
    processor.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        processor.stop()
