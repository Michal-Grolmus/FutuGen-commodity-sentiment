"""Baseline predictors for honest evaluation.

Every baseline has the same shape:
    def predict(event: dict) -> tuple[str, float]:  # (direction, confidence)

The direction is one of: "bullish", "bearish", "neutral".
Confidence is in [0, 1] — represents how strong the baseline thinks the prediction is.

If the LLM can't beat these, it's not worth the API cost.
"""
from __future__ import annotations

import hashlib
import random

# Keyword dictionaries calibrated on commodity news vocabulary
BULLISH_KEYWORDS = {
    "cut", "cuts", "reduction", "production cut", "supply cut", "sanctions",
    "attack", "strike", "halt", "shutdown", "disruption", "drought",
    "shortage", "deficit", "squeeze", "tight", "tightening supply",
    "invasion", "war", "escalation", "hurricane", "storm", "freeze",
    "stimulus", "easing", "qe", "rate cut", "dovish", "cuts rates",
    "ban", "embargo", "pipeline attack", "refinery", "blockade",
    "record low", "lowest", "safe haven", "safe-haven",
}

BEARISH_KEYWORDS = {
    "increase", "build", "surplus", "glut", "oversupply", "exports rise",
    "release", "spr release", "tariff", "tariffs", "hike", "rate hike",
    "hawkish", "tightening", "inventory build", "record high production",
    "peace", "deal", "agreement", "ceasefire", "truce",
    "recession", "demand destruction", "weak demand",
    "production increase", "expansion", "supply surge",
    "dollar strong", "dollar surge", "rate hike",
}


def _tokens(text: str) -> set[str]:
    """Simple lowercase token set with common phrase matching."""
    text = text.lower()
    tokens = set(text.split())
    # Check 2-word phrases
    words = text.split()
    tokens.update(f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1))
    return tokens


def predict_random(event: dict) -> tuple[str, float]:
    """Deterministic-random baseline seeded by event_id for reproducibility."""
    seed = int(hashlib.md5(event["event_id"].encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    direction = rng.choice(["bullish", "bearish", "neutral"])
    return direction, 0.33


def predict_always_bullish(event: dict) -> tuple[str, float]:
    """Commodities have slight upward drift long-term."""
    return "bullish", 0.50


def predict_keyword_sentiment(event: dict) -> tuple[str, float]:
    """Count bullish vs bearish keywords in news_text."""
    text = event.get("news_text", "")
    tokens = _tokens(text)
    bull = sum(1 for kw in BULLISH_KEYWORDS if kw in tokens)
    bear = sum(1 for kw in BEARISH_KEYWORDS if kw in tokens)

    if bull == 0 and bear == 0:
        return "neutral", 0.40
    if bull > bear:
        conf = min(0.5 + 0.1 * (bull - bear), 0.90)
        return "bullish", conf
    if bear > bull:
        conf = min(0.5 + 0.1 * (bear - bull), 0.90)
        return "bearish", conf
    return "neutral", 0.40


BASELINES = {
    "random": predict_random,
    "always_bullish": predict_always_bullish,
    "keyword": predict_keyword_sentiment,
}


def run_baseline(name: str, events: list[dict]) -> list[dict]:
    """Apply a baseline predictor to a list of events.

    Returns list of prediction dicts shaped like the LLM output:
      {event_id, commodity, direction, confidence, source="baseline:<name>"}
    """
    if name not in BASELINES:
        raise ValueError(f"Unknown baseline: {name}")
    predictor = BASELINES[name]
    preds = []
    for ev in events:
        direction, confidence = predictor(ev)
        preds.append({
            "event_id": ev["event_id"],
            "commodity": ev["commodity"],
            "direction": direction,
            "confidence": confidence,
            "source": f"baseline:{name}",
        })
    return preds
