"""Grade predictions against ground truth + actual market movement.

Inputs:
  predictions: [{event_id, commodity, direction, confidence, ...}]
  events:      [{event_id, date, commodity, expected_direction, prices{d0..d30}, ...}]

Outputs a list of graded predictions augmented with:
  - expected_direction (analyst label)
  - correct_label           — direction matches analyst label
  - actual_direction_d{h}   — derived from real market move per horizon
  - correct_market_d{h}     — direction matches actual market move
  - return_d{h}             — signed return for direction (useful for P&L)
"""
from __future__ import annotations

from typing import Any

NEUTRAL_THRESHOLD_PCT = 0.5
HORIZONS = [1, 3, 7, 14, 30]


def derive_actual_direction(price_then: float, price_now: float) -> str:
    """Classify a price move as bullish/bearish/neutral using NEUTRAL_THRESHOLD_PCT."""
    if price_then <= 0:
        return "neutral"
    change_pct = (price_now - price_then) / price_then * 100.0
    if abs(change_pct) < NEUTRAL_THRESHOLD_PCT:
        return "neutral"
    return "bullish" if change_pct > 0 else "bearish"


def grade(
    predictions: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Grade each prediction. Uses `event_id` to join."""
    events_by_id = {e["event_id"]: e for e in events}
    graded: list[dict[str, Any]] = []
    for p in predictions:
        ev = events_by_id.get(p["event_id"])
        if ev is None:
            continue
        g = dict(p)
        g["expected_direction"] = ev.get("expected_direction")
        g["date"] = ev.get("date")
        g["correct_label"] = g.get("direction") == g["expected_direction"]

        prices = ev.get("prices", {})
        d0 = prices.get("d0")
        if d0 is None:
            graded.append(g)
            continue

        for h in HORIZONS:
            price_h = prices.get(f"d{h}")
            if price_h is None:
                g[f"actual_direction_d{h}"] = None
                g[f"correct_market_d{h}"] = None
                g[f"return_d{h}"] = None
                continue
            actual = derive_actual_direction(float(d0), float(price_h))
            g[f"actual_direction_d{h}"] = actual
            g[f"correct_market_d{h}"] = g.get("direction") == actual
            # signed return: + if direction matched move, - otherwise
            pct = (float(price_h) - float(d0)) / float(d0) * 100.0
            if g.get("direction") == "bullish":
                g[f"return_d{h}"] = pct
            elif g.get("direction") == "bearish":
                g[f"return_d{h}"] = -pct
            else:
                g[f"return_d{h}"] = 0.0

        graded.append(g)
    return graded


def aggregate_accuracy(graded: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute accuracy vs. label + vs. market across all horizons."""
    n = len(graded)
    if n == 0:
        return {"count": 0}

    label_correct = sum(1 for g in graded if g.get("correct_label"))

    per_horizon = {}
    for h in HORIZONS:
        evaluable = [g for g in graded if g.get(f"correct_market_d{h}") is not None]
        if not evaluable:
            per_horizon[f"d{h}"] = {"count": 0, "accuracy": None}
            continue
        correct = sum(1 for g in evaluable if g[f"correct_market_d{h}"])
        per_horizon[f"d{h}"] = {
            "count": len(evaluable),
            "correct": correct,
            "accuracy": correct / len(evaluable),
        }

    return {
        "count": n,
        "accuracy_vs_label": label_correct / n,
        "per_horizon": per_horizon,
    }
