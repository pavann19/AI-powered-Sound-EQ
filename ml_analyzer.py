"""
Buffers system audio and classifies it with YAMNet, running on the LiteRT
(TFLite) interpreter rather than full TensorFlow.

Why this instead of `tensorflow` + `tensorflow_hub`: on this machine, cold
`import tensorflow` alone measured ~27-30s (full TF pulls in Keras, the
SavedModel loader, and a large native runtime -- something in that chain,
likely antivirus scanning the DLL tree, made every import slow here).
`ai_edge_litert` is a ~18MB wheel that's just an inference interpreter; the
same model, converted to .tflite, imports and loads in well under a second
and answers in ~10ms per window on CPU. Total measured cold start:
~40s -> ~0.4s for import+load.

The .tflite model is the officially published YAMNet export
(google/lite-model/yamnet/tflite/1) and exposes the same three outputs as
the SavedModel version -- scores, embeddings, spectrogram -- so nothing
downstream (intelligence.py, preference_model.py) needed to change: the
1024-dim embedding this produces is bit-for-bit the same shape and role.

Trade-off worth knowing: TFLite's YAMNet is int8/float32 quantized for
on-device inference. Classification quality is very close to the full
model (that's the point of the official export) but not guaranteed
numerically identical for edge-case audio.
"""

import os
import csv
import io
import urllib.request

import numpy as np
from scipy.signal import resample
from ai_edge_litert.interpreter import Interpreter

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tflite_cache")
_MODEL_PATH = os.path.join(_CACHE_DIR, "yamnet.tflite")
_CLASS_MAP_PATH = os.path.join(_CACHE_DIR, "yamnet_class_map.csv")

_MODEL_URL = "https://tfhub.dev/google/lite-model/yamnet/tflite/1?lite-format=tflite"
_CLASS_MAP_URL = (
    "https://raw.githubusercontent.com/tensorflow/models/master/"
    "research/audioset/yamnet/yamnet_class_map.csv"
)


def _ensure_cached(path: str, url: str, what: str):
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print(f"Downloading {what} (first run only, cached after)...")
    urllib.request.urlretrieve(url, path)


class YAMNetAnalyzer:
    """
    Buffers system audio, resamples to 16kHz, and uses YAMNet to classify
    the dominant audio event (genre/mood/speech).
    """
    def __init__(self, sample_rate=44100, buffer_seconds=0.975):
        _ensure_cached(_MODEL_PATH, _MODEL_URL, "YAMNet model")
        _ensure_cached(_CLASS_MAP_PATH, _CLASS_MAP_URL, "YAMNet class map")

        self.interpreter = Interpreter(model_path=_MODEL_PATH)
        self.class_names = self._load_class_names()

        self.sample_rate = sample_rate
        self.target_rate = 16000
        # How many samples at the input sample rate are needed for the buffer
        self.buffer_size = int(self.sample_rate * buffer_seconds)
        self.audio_buffer = np.zeros(0, dtype=np.float32)

        self._input_index = self.interpreter.get_input_details()[0]["index"]
        out_details = self.interpreter.get_output_details()
        self._scores_index = out_details[0]["index"]
        self._embeddings_index = out_details[1]["index"]
        self._resized_for = None  # last input length the interpreter was allocated for

    def _load_class_names(self):
        with open(_CLASS_MAP_PATH, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [row["display_name"] for row in reader]

    def process_chunk(self, chunk):
        """
        Takes a new chunk of audio, adds it to the buffer.
        If the buffer has enough data, it runs YAMNet and returns the top class name.
        Otherwise returns None.
        """
        # Downmix to mono if stereo
        if chunk.ndim > 1:
            chunk = chunk.mean(axis=1)

        self.audio_buffer = np.concatenate([self.audio_buffer, chunk])

        # Once we have enough audio for a solid prediction (~1 sec)
        if len(self.audio_buffer) >= self.buffer_size:
            process_data = self.audio_buffer[:self.buffer_size]

            # Keep the remainder in the buffer
            self.audio_buffer = self.audio_buffer[self.buffer_size:]

            # Resample to 16kHz for YAMNet
            num_samples_16k = int(len(process_data) * self.target_rate / self.sample_rate)
            resampled = resample(process_data, num_samples_16k).astype(np.float32)

            # The interpreter's input tensor is fixed-size once allocated;
            # only re-resize (which re-allocates) when the length actually
            # changes, which in steady state is never after the first call.
            if self._resized_for != len(resampled):
                self.interpreter.resize_tensor_input(self._input_index, [len(resampled)])
                self.interpreter.allocate_tensors()
                self._resized_for = len(resampled)

            self.interpreter.set_tensor(self._input_index, resampled)
            self.interpreter.invoke()

            scores = self.interpreter.get_tensor(self._scores_index)       # (frames, 521)
            embeddings = self.interpreter.get_tensor(self._embeddings_index)  # (frames, 1024)

            # Average the scores over all frames (if multiple)
            mean_scores = np.mean(scores, axis=0)

            # Get top 5 classes
            top5_indices = np.argsort(mean_scores)[::-1][:5]

            predictions = []
            for idx in top5_indices:
                predictions.append({
                    "class_name": self.class_names[idx],
                    "confidence": float(mean_scores[idx])
                })

            mean_embedding = np.mean(embeddings, axis=0)

            return {
                "predictions": predictions,
                "embedding": mean_embedding.tolist()
            }

        return None
