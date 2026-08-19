"""
Local audio fingerprint cache using Chromaprint. Recognizes a track
you've already heard and instantly recalls the preset chosen for it
last time, instead of re-running analysis from scratch every play.

Requires:
    pip install pyacoustid
    Chromaprint's `fpcalc` binary on PATH (or set the FPCALC env var).
    Download: https://acoustid.org/chromaprint

Everything stays local in eq_cache.db (SQLite) -- fingerprint
*generation* needs no internet access or API key. We never call the
AcoustID web lookup service; we're only using Chromaprint's fingerprint
algorithm as a "have I heard this exact audio before" hash, not for
metadata identification.

If pyacoustid / fpcalc isn't installed, this module is meant to be
imported inside a try/except in main.py and skipped gracefully -- the
rest of the pipeline works fine without it.
"""

import sqlite3
import time
import numpy as np

try:
    import acoustid
    HAVE_ACOUSTID = True
except ImportError:
    HAVE_ACOUSTID = False

DB_PATH = "eq_cache.db"
FINGERPRINT_SECONDS = 12  # Chromaprint wants a reasonably long sample to be reliable


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_presets (
            fingerprint TEXT PRIMARY KEY,
            preset TEXT NOT NULL,
            play_count INTEGER DEFAULT 1,
            last_used REAL
        )
    """)
    return conn


class FingerprintCache:
    def __init__(self, db_path: str = DB_PATH, sample_rate: int = 44100):
        if not HAVE_ACOUSTID:
            raise RuntimeError(
                "pyacoustid not installed or fpcalc not found on PATH. "
                "Run `pip install pyacoustid` and install Chromaprint's "
                "fpcalc binary, or leave this module disabled for now."
            )
        self.conn = _connect(db_path)
        self.sample_rate = sample_rate
        self._buffer = []
        self._buffered_seconds = 0.0

    def feed(self, chunk: np.ndarray):
        """Accumulate audio; once ~FINGERPRINT_SECONDS is buffered,
        fingerprint it and reset. Returns a fingerprint string when
        ready, otherwise None (most calls)."""
        mono = chunk.mean(axis=1) if chunk.ndim > 1 else chunk
        self._buffer.append(mono)
        self._buffered_seconds += len(mono) / self.sample_rate

        if self._buffered_seconds < FINGERPRINT_SECONDS:
            return None

        full = np.concatenate(self._buffer)
        self._buffer = []
        self._buffered_seconds = 0.0

        pcm_int16 = (full * 32767).astype(np.int16).tobytes()
        try:
            _, fp = acoustid.fingerprint(self.sample_rate, 1, pcm_int16)
            return fp.decode() if isinstance(fp, bytes) else fp
        except Exception:
            return None  # fingerprinting can fail on silence/odd buffers -- just skip this cycle

    def lookup(self, fingerprint: str):
        row = self.conn.execute(
            "SELECT preset FROM track_presets WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        return row[0] if row else None

    def remember(self, fingerprint: str, preset: str):
        self.conn.execute("""
            INSERT INTO track_presets (fingerprint, preset, play_count, last_used)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                preset = excluded.preset,
                play_count = play_count + 1,
                last_used = excluded.last_used
        """, (fingerprint, preset, time.time()))
        self.conn.commit()
