"""
Learns your actual preset preferences from manual overrides, instead of
relying purely on the hand-tuned keyword/spectral rules in intelligence.py.

Every time you manually pick a preset, that's a labeled example: "given what
YAMNet heard right then (its 1024-dim embedding), this is the preset I
wanted." Once enough examples accumulate, a small softmax classifier trains
on them and its predictions get blended into the decision fusion in
intelligence.py -- so the system gradually shifts from "generic rules" toward
"what you've actually chosen for audio like this before."

No sklearn dependency: this is a small enough problem (at most a few hundred
examples, 1024 input dims, one class per preset) that a hand-rolled numpy
softmax classifier trains in well under 100ms, which avoids pulling in a new
heavy library just for this.
"""

import os
import numpy as np

from eq_presets import PRESETS

DATA_PATH = "preference_data.npz"
MIN_SAMPLES = 6      # total examples needed before the model starts voting
L2 = 1e-3
EPOCHS = 400
LR = 0.05


class PreferenceModel:
    def __init__(self, path: str = DATA_PATH):
        self.path = path
        self.classes = list(PRESETS.keys())
        self._class_index = {c: i for i, c in enumerate(self.classes)}

        self.embeddings = np.zeros((0, 1), dtype=np.float32)  # widened on first example
        self.labels = np.zeros((0,), dtype=np.int64)
        self.weights = None   # trained (d+1, k) matrix, or None until ready
        self._mu = None
        self._sigma = None

        self._load()
        if len(self.labels) >= MIN_SAMPLES:
            self._retrain()

    # ── Persistence ──────────────────────────────────────────────────
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            data = np.load(self.path, allow_pickle=True)
            emb = data["embeddings"]
            lbl = data["labels"]
            # Drop rows whose label is a preset that no longer exists, e.g.
            # eq_presets.py was edited since this file was last written.
            keep = [i for i, l in enumerate(lbl) if str(l) in self._class_index]
            if keep:
                self.embeddings = emb[keep].astype(np.float32)
                self.labels = np.array(
                    [self._class_index[str(lbl[i])] for i in keep], dtype=np.int64
                )
        except Exception as e:
            print(f"[preference model] failed to load {self.path}: {e}")

    def _save(self):
        try:
            label_names = np.array([self.classes[i] for i in self.labels], dtype=object)
            np.savez(self.path, embeddings=self.embeddings, labels=label_names)
        except Exception as e:
            print(f"[preference model] failed to save {self.path}: {e}")

    # ── Training data ────────────────────────────────────────────────
    def add_example(self, embedding, preset_id: str):
        if preset_id not in self._class_index:
            return
        vec = np.asarray(embedding, dtype=np.float32).reshape(1, -1)

        if self.embeddings.shape[0] == 0:
            self.embeddings = vec
        elif vec.shape[1] != self.embeddings.shape[1]:
            return  # embedding dimensionality changed -- don't corrupt the dataset
        else:
            self.embeddings = np.vstack([self.embeddings, vec])

        self.labels = np.append(self.labels, self._class_index[preset_id])
        self._save()
        if len(self.labels) >= MIN_SAMPLES:
            self._retrain()

    @property
    def ready(self) -> bool:
        return self.weights is not None

    @property
    def sample_count(self) -> int:
        return int(len(self.labels))

    # ── Training ─────────────────────────────────────────────────────
    def _retrain(self):
        X = self.embeddings
        y = self.labels
        n, d = X.shape
        k = len(self.classes)

        # Standardize -- raw YAMNet embedding activations aren't zero-centered
        # or unit-scale, and gradient descent on them directly converges far
        # more slowly (and less stably) than on standardized features.
        mu = X.mean(axis=0)
        sigma = X.std(axis=0) + 1e-6
        Xs = (X - mu) / sigma
        Xb = np.hstack([Xs, np.ones((n, 1), dtype=np.float32)])  # bias column

        W = np.zeros((d + 1, k), dtype=np.float32)
        Y = np.zeros((n, k), dtype=np.float32)
        Y[np.arange(n), y] = 1.0

        for _ in range(EPOCHS):
            logits = Xb @ W
            logits -= logits.max(axis=1, keepdims=True)
            probs = np.exp(logits)
            probs /= probs.sum(axis=1, keepdims=True)
            grad = Xb.T @ (probs - Y) / n + L2 * W
            W -= LR * grad

        self.weights = W
        self._mu = mu
        self._sigma = sigma

    # ── Inference ────────────────────────────────────────────────────
    def predict_scores(self, embedding) -> dict:
        """Returns {preset_id: probability} (sums to ~1.0), or {} if the
        model hasn't trained yet or the embedding shape doesn't match."""
        if self.weights is None:
            return {}
        vec = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        if vec.shape[1] != self._mu.shape[0]:
            return {}
        xs = (vec - self._mu) / self._sigma
        xb = np.hstack([xs, np.ones((1, 1), dtype=np.float32)])
        logits = xb @ self.weights
        logits -= logits.max()
        probs = np.exp(logits)
        probs /= probs.sum()
        return {self.classes[i]: float(probs[0, i]) for i in range(len(self.classes))}
