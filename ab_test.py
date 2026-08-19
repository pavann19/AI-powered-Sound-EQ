"""
Blind A/B listening test.

The manual bypass toggle from before answers "can I hear a difference right
now" -- useful, but you always know which state you're in, so expectation
bias is doing a lot of the work. This runs a proper blind protocol instead:

  - Each round randomly assigns EQ-on or bypass, *not shown to the listener*.
  - After a fixed listening window, you rate what you heard ("sounds good" /
    "sounds off") with no idea which condition produced it.
  - Over enough rounds, comparing the approval rate of EQ-on rounds against
    bypass rounds answers the actual question: is the processing helping,
    hurting, or doing nothing you can perceive.

Results persist across sessions so the sample size builds up over time
rather than resetting every launch.
"""

import os
import json
import time
import random

RESULTS_PATH = "ab_test_results.json"
DEFAULT_ROUND_SECONDS = 12.0
MIN_SAMPLES_FOR_VERDICT = 10  # per condition, before we'll say anything directional


class ABTestSession:
    def __init__(self, processor, round_seconds: float = DEFAULT_ROUND_SECONDS, path: str = RESULTS_PATH):
        self.processor = processor
        self.round_seconds = round_seconds
        self.path = path

        self.active = False
        self.round_state_bypass = None   # True/False for the CURRENT round; None if no round running
        self.round_start = 0.0
        self.round_index = 0
        self.pending_rating = False      # round's listening window elapsed, waiting on rate()
        self._pre_test_bypass = False    # so stop() can restore whatever was active before

        self.results = self._load()

    # ── Persistence ──────────────────────────────────────────────────
    def _load(self):
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return [r for r in data if isinstance(r, dict) and "eq_on" in r and "approved" in r]
        except Exception as e:
            print(f"[ab test] failed to load {self.path}: {e}")
            return []

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.results, f, indent=2)
        except Exception as e:
            print(f"[ab test] failed to save {self.path}: {e}")

    # ── Lifecycle ────────────────────────────────────────────────────
    def start(self):
        if self.active:
            return
        self.active = True
        self._pre_test_bypass = self.processor.bypass
        self.round_index = 0
        self._new_round()

    def stop(self):
        self.active = False
        self.pending_rating = False
        self.round_state_bypass = None
        # Leave audio in whatever state it was before the test started,
        # rather than stranding it mid-round on a random condition.
        self.processor.set_bypass(self._pre_test_bypass)

    def _new_round(self):
        self.round_index += 1
        self.round_state_bypass = random.choice([True, False])
        self.processor.set_bypass(self.round_state_bypass)
        self.round_start = time.time()
        self.pending_rating = False

    def tick(self) -> float:
        """Call periodically from the UI. Returns seconds remaining in the
        current round (0.0 once a rating is due). No-op / returns 0.0 if
        the test isn't active."""
        if not self.active:
            return 0.0
        if self.pending_rating:
            return 0.0
        remaining = self.round_seconds - (time.time() - self.round_start)
        if remaining <= 0:
            self.pending_rating = True
            return 0.0
        return remaining

    def rate(self, approved: bool):
        """Log the listener's blind judgment of the round that just finished,
        then start the next round."""
        if not self.active or not self.pending_rating:
            return
        self.results.append({
            "eq_on": not self.round_state_bypass,
            "approved": approved,
            "timestamp": time.time(),
        })
        self._save()
        self._new_round()

    # ── Reporting ────────────────────────────────────────────────────
    def summary(self) -> dict:
        eq = [r for r in self.results if r["eq_on"]]
        by = [r for r in self.results if not r["eq_on"]]
        eq_n, by_n = len(eq), len(by)
        eq_rate = (sum(1 for r in eq if r["approved"]) / eq_n) if eq_n else None
        by_rate = (sum(1 for r in by if r["approved"]) / by_n) if by_n else None

        verdict = "Keep listening"
        if eq_n >= MIN_SAMPLES_FOR_VERDICT and by_n >= MIN_SAMPLES_FOR_VERDICT:
            diff = eq_rate - by_rate
            # A plain-language directional read, not a claimed significance
            # test -- with these sample sizes a formal test would mostly just
            # report "can't tell," which isn't more useful to act on.
            if diff >= 0.20:
                verdict = "EQ clearly preferred"
            elif diff >= 0.08:
                verdict = "EQ mildly preferred"
            elif diff <= -0.20:
                verdict = "Bypass clearly preferred"
            elif diff <= -0.08:
                verdict = "Bypass mildly preferred"
            else:
                verdict = "No perceptible difference"

        return {
            "total": len(self.results),
            "eq_n": eq_n, "eq_rate": eq_rate,
            "bypass_n": by_n, "bypass_rate": by_rate,
            "verdict": verdict,
        }
