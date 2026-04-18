"""Tests for horizon analysis module."""
from __future__ import annotations

import pytest

from evaluation.horizon_analysis import (
    adaptive_horizon_accuracy,
    all_horizon_correct,
    analyze_all,
    any_horizon_correct,
    mae_mfe,
    optimal_horizon_per_event_type,
    signal_persistence,
    time_to_peak,
)


def _make_graded(event_id, direction, returns, correctness):
    """Helper to build a graded entry with per-horizon returns and correctness."""
    g = {"event_id": event_id, "direction": direction}
    for h, r in returns.items():
        g[f"return_d{h}"] = r
    for h, c in correctness.items():
        g[f"correct_market_d{h}"] = c
    return g


def test_any_horizon_correct_true_if_any_match():
    graded = [
        _make_graded("a", "bullish", {1: 2.0, 3: -1.0, 7: -2.0, 14: -3.0, 30: -4.0},
                     {1: True, 3: False, 7: False, 14: False, 30: False}),
        _make_graded("b", "bullish", {1: -1.0, 3: -2.0, 7: -3.0, 14: -4.0, 30: -5.0},
                     {1: False, 3: False, 7: False, 14: False, 30: False}),
    ]
    result = any_horizon_correct(graded)
    assert result["n"] == 2
    assert result["any_hit"] == pytest.approx(0.5)


def test_all_horizon_correct_only_if_every_match():
    graded = [
        _make_graded("a", "bullish", {1: 1, 3: 1, 7: 1, 14: 1, 30: 1},
                     {1: True, 3: True, 7: True, 14: True, 30: True}),
        _make_graded("b", "bullish", {1: 1, 3: 1, 7: 1, 14: 1, 30: 1},
                     {1: True, 3: True, 7: True, 14: True, 30: False}),
    ]
    result = all_horizon_correct(graded)
    assert result["all_hit"] == pytest.approx(0.5)


def test_signal_persistence_baseline_d1_is_one():
    graded = [
        _make_graded("a", "bullish", {1: 1, 3: 1, 7: 1, 14: 1, 30: 1},
                     {1: True, 3: True, 7: False, 14: False, 30: False}),
        _make_graded("b", "bullish", {1: 1, 3: 1, 7: 1, 14: 1, 30: 1},
                     {1: True, 3: False, 7: False, 14: False, 30: False}),
    ]
    result = signal_persistence(graded)
    assert result["d1_given_d1"] == pytest.approx(1.0)
    assert result["d3_given_d1"] == pytest.approx(0.5)
    assert result["d7_given_d1"] == pytest.approx(0.0)


def test_signal_persistence_empty():
    result = signal_persistence([])
    assert result["d1_given_d1"] is None


def test_time_to_peak_finds_max_return_horizon():
    graded = [
        _make_graded("a", "bullish", {1: 1.0, 3: 3.0, 7: 2.0, 14: 1.5, 30: 1.0},
                     {1: True, 3: True, 7: True, 14: True, 30: True}),
        _make_graded("b", "bullish", {1: 0.5, 3: 0.4, 7: 0.3, 14: 0.2, 30: 5.0},
                     {1: True, 3: True, 7: True, 14: True, 30: True}),
    ]
    result = time_to_peak(graded)
    assert result["n"] == 2
    # Mean of d3 and d30 = 16.5
    assert result["mean_peak_horizon"] == pytest.approx(16.5)
    assert result["distribution"]["d3"] == 1
    assert result["distribution"]["d30"] == 1


def test_time_to_peak_ignores_neutral():
    graded = [
        _make_graded("a", "neutral", {1: 0, 3: 0, 7: 0, 14: 0, 30: 0},
                     {1: True, 3: True, 7: True, 14: True, 30: True}),
    ]
    result = time_to_peak(graded)
    assert result["n"] == 0


def test_mae_mfe_computes_asymmetric_payoff():
    graded = [
        _make_graded("a", "bullish", {1: 2.0, 3: 3.0, 7: -1.0, 14: 1.0, 30: 5.0},
                     {1: True, 3: True, 7: False, 14: True, 30: True}),
    ]
    result = mae_mfe(graded)
    assert result["n"] == 1
    assert result["avg_mfe_pct"] == pytest.approx(5.0)
    assert result["avg_mae_pct"] == pytest.approx(-1.0)
    assert result["ratio_mfe_mae"] == pytest.approx(5.0)


def test_optimal_horizon_per_event_type_learns_from_train_cal():
    events = [
        {"event_id": "e1", "event_type": "monetary"},
        {"event_id": "e2", "event_type": "monetary"},
        {"event_id": "e3", "event_type": "opec"},
        {"event_id": "e4", "event_type": "opec"},
    ]
    graded = [
        # monetary: d7 is best (2/2 right)
        _make_graded("e1", "bullish", {1: 0, 3: 0, 7: 0, 14: 0, 30: 0},
                     {1: False, 3: False, 7: True, 14: False, 30: False}),
        _make_graded("e2", "bullish", {1: 0, 3: 0, 7: 0, 14: 0, 30: 0},
                     {1: False, 3: False, 7: True, 14: False, 30: False}),
        # opec: d1 is best (2/2 right)
        _make_graded("e3", "bullish", {1: 0, 3: 0, 7: 0, 14: 0, 30: 0},
                     {1: True, 3: False, 7: False, 14: False, 30: False}),
        _make_graded("e4", "bullish", {1: 0, 3: 0, 7: 0, 14: 0, 30: 0},
                     {1: True, 3: False, 7: False, 14: False, 30: False}),
    ]
    result = optimal_horizon_per_event_type(graded, events)
    assert result["monetary"]["best_horizon"] == 7
    assert result["monetary"]["best_accuracy"] == 1.0
    assert result["opec"]["best_horizon"] == 1
    assert result["opec"]["best_accuracy"] == 1.0


def test_adaptive_horizon_accuracy_beats_fixed_when_appropriate():
    events = [
        {"event_id": "e1", "event_type": "opec"},
    ]
    horizon_map = {"opec": {"best_horizon": 1, "best_accuracy": 1.0, "n_samples": 5}}
    graded_test = [
        # Correct at d1 (OPEC's optimal) but wrong at d7 (the fixed)
        _make_graded("e1", "bullish", {1: 1, 3: 0, 7: 0, 14: 0, 30: 0},
                     {1: True, 3: False, 7: False, 14: False, 30: False}),
    ]
    result = adaptive_horizon_accuracy(graded_test, events, horizon_map)
    assert result["adaptive_accuracy"] == 1.0
    assert result["fixed_d7_accuracy"] == 0.0
    assert result["uplift"] == 1.0


def test_analyze_all_returns_complete_structure():
    events = [{"event_id": "e1", "event_type": "monetary"}]
    graded = [
        _make_graded("e1", "bullish", {1: 2.0, 3: 1.0, 7: 0.5, 14: 0.0, 30: -1.0},
                     {1: True, 3: True, 7: False, 14: False, 30: False}),
    ]
    result = analyze_all(graded, graded, events)
    assert "any_horizon" in result
    assert "all_horizons" in result
    assert "signal_persistence" in result
    assert "time_to_peak" in result
    assert "mae_mfe" in result
    assert "optimal_horizon_per_type" in result
    assert "adaptive_vs_fixed" in result
