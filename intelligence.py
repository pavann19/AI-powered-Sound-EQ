from eq_presets import PRESETS

class IntelligenceEngine:
    """
    Fuses top-5 YAMNet predictions, spectral energy ratios, and (once it has
    enough examples) a learned preference model into a compatibility score
    for each preset.
    """
    def __init__(self):
        # We define some keyword mappings to presets for the YAMNet side
        self.preset_keywords = {
            "vocal_mid": ['speech', 'voice', 'vocal', 'conversation', 'narration', 'podcast'],
            "bass_boost": ['hip hop', 'electronic', 'dance', 'techno', 'bass', 'dubstep', 'drum and bass'],
            "v_shape": ['rock', 'pop', 'metal', 'punk', 'electric guitar', 'synthesizer'],
            "treble_smooth": ['classical', 'acoustic', 'piano', 'violin', 'orchestra', 'ambient', 'jazz'],
        }

    def evaluate(self, ml_predictions, spectral_ratios, embedding=None, preference_model=None):
        """
        ml_predictions: list of dicts {"class_name": str, "confidence": float}
        spectral_ratios: dict of band names to ratios (0.0 to 1.0)
        embedding: optional 1024-dim YAMNet embedding for this window
        preference_model: optional PreferenceModel trained on your manual
            preset choices; ignored until it has enough examples to predict

        Returns:
            dict with best_preset, scores (dict of preset -> score 0-100)
        """
        scores = {p: 0.0 for p in PRESETS.keys()}

        pref_scores = {}
        if preference_model is not None and embedding is not None and preference_model.ready:
            pref_scores = preference_model.predict_scores(embedding)

        # Once the learned model has something to say, it carries as much
        # weight as the generic keyword rules did on their own -- rules and
        # spectral shape still vote, but they no longer dominate a signal
        # that's actually trained on what you've picked before.
        if pref_scores:
            w_ml, w_spectral, w_pref = 40.0, 20.0, 40.0
        else:
            w_ml, w_spectral, w_pref = 70.0, 30.0, 0.0

        # 1. Evaluate ML Predictions
        # For each prediction, if it matches a preset's keywords, add to that preset's score
        for pred in ml_predictions:
            cls = pred["class_name"].lower()
            conf = pred["confidence"]

            matched = False
            for preset_id, keywords in self.preset_keywords.items():
                if any(kw in cls for kw in keywords):
                    scores[preset_id] += conf * w_ml
                    matched = True
                    break # only match first

            if not matched:
                # If it doesn't map to anything specific, favor balanced
                scores["balanced"] += conf * w_ml

        # 2. Evaluate Spectral Ratios
        # We give a boost based on what frequencies are currently dominant

        # If there's a lot of bass energy naturally, bass_boost is highly compatible
        bass_energy = spectral_ratios.get("sub_bass", 0) + spectral_ratios.get("bass", 0)
        scores["bass_boost"] += min(bass_energy * 2.0 * w_spectral, w_spectral)

        # If there's a lot of mid energy (vocals)
        mid_energy = spectral_ratios.get("mid", 0)
        scores["vocal_mid"] += min(mid_energy * 2.0 * w_spectral, w_spectral)

        # If there's a lot of high frequency (needs smoothing)
        high_energy = spectral_ratios.get("treble", 0)
        scores["treble_smooth"] += min(high_energy * 2.0 * w_spectral, w_spectral)

        # V-shape likes both highs and lows
        v_energy = bass_energy + high_energy
        scores["v_shape"] += min(v_energy * 1.5 * w_spectral, w_spectral)

        # Balanced gets a baseline boost from evenly distributed energy
        # Or just a flat baseline to keep it competitive
        scores["balanced"] += w_spectral * 0.5

        # 3. Learned preference model
        if pref_scores:
            for preset_id, prob in pref_scores.items():
                if preset_id in scores:
                    scores[preset_id] += prob * w_pref

        # Normalize scores to 0-100 scale
        max_score = max(scores.values()) if scores.values() else 1.0
        if max_score > 0:
            for k in scores:
                scores[k] = (scores[k] / max_score) * 100.0

        # Determine best. When nothing scored (e.g. no ML predictions yet and
        # near-silent spectral ratios), fall back to "balanced" explicitly
        # instead of whichever preset happens to be first in dict order.
        if max_score > 0:
            best_preset = max(scores, key=scores.get)
        else:
            best_preset = "balanced"

        return {
            "best_preset": best_preset,
            "scores": {k: round(v, 1) for k, v in scores.items()},
            "learned": bool(pref_scores),
        }
