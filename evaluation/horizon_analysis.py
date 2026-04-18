"""Horizon-optimization analysis.

Answers: "is a wrong prediction at d=7 actually right at d=1 or d=14?"
This matters because different event types have different natural timescales
— a supply shock spikes + reverts in days, while a Fed pivot takes weeks to
price in. Fixed-horizon evaluation can systematically under-count correct
predictions evaluated at the wrong clock.

Metrics produced:
  - any_horizon_hit_rate      — fraction correct at ANY of d1..d30
  - all_horizon_hit_rate      — fraction correct at EVERY horizon (durable)
  - signal_persistence        — P(correct at d_h | correct at d_1)
  - time_to_peak              — mean horizon where the trade return peaks
  - optimal_horizon_per_type  — event-type → best horizon (from TRAIN+CAL,
                                no look-ahead)
  - mae_mfe                   — max adverse / favorable excursion per trade
  - adaptive_accuracy         — accuracy on test when using per-type horizons
                                learned from train+cal
"""
from __future__ import annotations

from typing import Any

HORIZONS = [1, 3, 7, 14, 30]


def any_horizon_correct(graded: list[dict[str, Any]]) -> dict[str, float]:
    """Fraction correct at least at ONE horizon (loose bound)."""
    if not graded:
        return {"n": 0, "any_hit": 0.0}
    hits = 0
    for g in graded:
        if any(g.get(f"correct_market_d{h}") for h in HORIZONS):
            hits += 1
    return {"n": len(graded), "any_hit": hits / len(graded)}


def all_horizon_correct(graded: list[dict[str, Any]]) -> dict[str, float]:
    """Fraction correct at EVERY horizon — the durable-signal bound."""
    if not graded:
        return {"n": 0, "all_hit": 0.0}
    hits = 0
    for g in graded:
        if all(g.get(f"correct_market_d{h}") is True for h in HORIZONS):
            hits += 1
    return {"n": len(graded), "all_hit": hits / len(graded)}


def signal_persistence(graded: list[dict[str, Any]]) -> dict[str, float | None]:
    """P(correct at d_h | correct at d_1). Measures decay of the signal.

    If it stays ~1.0, signal is durable. If it drops to 0.5, signal is
    reverting (trade-then-exit regime). Computed only for items where d1
    was defined.
    """
    correct_d1 = [g for g in graded if g.get("correct_market_d1") is True]
    out: dict[str, float | None] = {"base_n_d1_correct": float(len(correct_d1))}
    if not correct_d1:
        for h in HORIZONS:
            out[f"d{h}_given_d1"] = None
        return out
    for h in HORIZONS:
        evaluable = [g for g in correct_d1 if g.get(f"correct_market_d{h}") is not None]
        if not evaluable:
            out[f"d{h}_given_d1"] = None
            continue
        still_correct = sum(1 for g in evaluable if g[f"correct_market_d{h}"])
        out[f"d{h}_given_d1"] = still_correct / len(evaluable)
    return out


def time_to_peak(graded: list[dict[str, Any]]) -> dict[str, Any]:
    """For each trade (correct OR incorrect direction), find the horizon
    where the signed return is maximal. Reports the distribution."""
    peak_horizons: list[int] = []
    for g in graded:
        if g.get("direction") not in ("bullish", "bearish"):
            continue
        returns = [(h, g.get(f"return_d{h}")) for h in HORIZONS]
        valid = [(h, r) for h, r in returns if r is not None]
        if not valid:
            continue
        peak_h = max(valid, key=lambda x: x[1])[0]
        peak_horizons.append(peak_h)
    if not peak_horizons:
        return {"n": 0, "mean_peak_horizon": None}
    from collections import Counter
    dist = Counter(peak_horizons)
    return {
        "n": len(peak_horizons),
        "mean_peak_horizon": sum(peak_horizons) / len(peak_horizons),
        "distribution": {f"d{h}": dist.get(h, 0) for h in HORIZONS},
    }


def optimal_horizon_per_event_type(
    graded_train_cal: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """On train+cal data, find the horizon with best accuracy per event_type.

    NO LOOK-AHEAD: learned only from train+cal, applied to test separately.
    Returns {event_type: {best_horizon, acc, counts_per_horizon}}.
    """
    events_by_id = {e["event_id"]: e for e in events}
    by_type: dict[str, list[dict[str, Any]]] = {}
    for g in graded_train_cal:
        ev = events_by_id.get(g["event_id"])
        if ev is None:
            continue
        et = ev.get("event_type", "unknown")
        by_type.setdefault(et, []).append(g)

    out: dict[str, dict[str, Any]] = {}
    for et, gs in by_type.items():
        scores: dict[int, dict[str, float]] = {}
        for h in HORIZONS:
            evaluable = [g for g in gs if g.get(f"correct_market_d{h}") is not None]
            if not evaluable:
                scores[h] = {"acc": 0.0, "n": 0}
                continue
            correct = sum(1 for g in evaluable if g[f"correct_market_d{h}"])
            scores[h] = {"acc": correct / len(evaluable), "n": len(evaluable)}
        best_h = max(scores, key=lambda h: scores[h]["acc"])
        out[et] = {
            "best_horizon": best_h,
            "best_accuracy": scores[best_h]["acc"],
            "n_samples": scores[best_h]["n"],
            "all_horizons": {f"d{h}": scores[h] for h in HORIZONS},
        }
    return out


def adaptive_horizon_accuracy(
    graded_test: list[dict[str, Any]],
    events: list[dict[str, Any]],
    horizon_map: dict[str, dict[str, Any]],
    default_horizon: int = 7,
) -> dict[str, Any]:
    """Apply the per-type horizon map (learned from train+cal) to test predictions.

    For each test prediction, look up optimal horizon by its event_type, then
    check if the prediction was correct at THAT horizon. Compare with the
    fixed-d7 baseline.
    """
    events_by_id = {e["event_id"]: e for e in events}
    adaptive_hits = 0
    fixed_hits = 0
    evaluable = 0
    per_event: list[dict[str, Any]] = []
    for g in graded_test:
        ev = events_by_id.get(g["event_id"])
        if ev is None:
            continue
        et = ev.get("event_type", "unknown")
        h = horizon_map.get(et, {}).get("best_horizon", default_horizon)
        a_correct = g.get(f"correct_market_d{h}")
        f_correct = g.get(f"correct_market_d{default_horizon}")
        if a_correct is None or f_correct is None:
            continue
        evaluable += 1
        if a_correct:
            adaptive_hits += 1
        if f_correct:
            fixed_hits += 1
        per_event.append({
            "event_id": g["event_id"],
            "event_type": et,
            "horizon_used": h,
            "adaptive_correct": bool(a_correct),
            "fixed_correct": bool(f_correct),
        })
    return {
        "n": evaluable,
        "adaptive_accuracy": adaptive_hits / evaluable if evaluable else 0.0,
        "fixed_d7_accuracy": fixed_hits / evaluable if evaluable else 0.0,
        "uplift": (adaptive_hits - fixed_hits) / evaluable if evaluable else 0.0,
        "per_event": per_event[:20],  # sample for report
    }


def mae_mfe(graded: list[dict[str, Any]]) -> dict[str, Any]:
    """Max Adverse / Favorable Excursion across the evaluated horizons.

    For each directional trade:
      - MFE = max signed return across horizons (best the trade got to)
      - MAE = min signed return (worst the trade dropped to)
    Reports average MFE, MAE, and ratio MFE/|MAE|.
    """
    mfes, maes = [], []
    for g in graded:
        if g.get("direction") not in ("bullish", "bearish"):
            continue
        rs = [g.get(f"return_d{h}") for h in HORIZONS]
        rs = [r for r in rs if r is not None]
        if not rs:
            continue
        mfes.append(max(rs))
        maes.append(min(rs))
    if not mfes:
        return {"n": 0}
    avg_mfe = sum(mfes) / len(mfes)
    avg_mae = sum(maes) / len(maes)
    return {
        "n": len(mfes),
        "avg_mfe_pct": avg_mfe,
        "avg_mae_pct": avg_mae,
        "ratio_mfe_mae": (avg_mfe / abs(avg_mae)) if avg_mae != 0 else None,
    }


def analyze_all(
    graded_test: list[dict[str, Any]],
    graded_train_cal: list[dict[str, Any]] | None,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose the full horizon-analysis section for the report."""
    out: dict[str, Any] = {
        "any_horizon": any_horizon_correct(graded_test),
        "all_horizons": all_horizon_correct(graded_test),
        "signal_persistence": signal_persistence(graded_test),
        "time_to_peak": time_to_peak(graded_test),
        "mae_mfe": mae_mfe(graded_test),
    }
    if graded_train_cal:
        horizon_map = optimal_horizon_per_event_type(graded_train_cal, events)
        out["optimal_horizon_per_type"] = horizon_map
        out["adaptive_vs_fixed"] = adaptive_horizon_accuracy(graded_test, events, horizon_map)
    return out
