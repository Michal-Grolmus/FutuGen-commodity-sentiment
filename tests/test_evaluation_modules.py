"""Unit tests for the professional backtest evaluation modules."""
from __future__ import annotations

import pytest

from evaluation.baselines import BASELINES, run_baseline
from evaluation.calibration import (
    apply_calibration,
    expected_calibration_error,
    fit_calibration,
)
from evaluation.grade import derive_actual_direction, grade
from evaluation.pnl import simulate, trade_return
from evaluation.splits import SplitConfig, split_events
from evaluation.statistics import (
    accuracy,
    binomial_two_sided_pvalue,
    bootstrap_ci,
    confusion_matrix,
    mcnemar_pvalue,
)

# ---------- splits ----------

def test_splits_by_date():
    events = [
        {"event_id": "a", "date": "2020-05-01"},
        {"event_id": "b", "date": "2022-06-15"},
        {"event_id": "c", "date": "2023-02-20"},
    ]
    train, calib, test = split_events(events, SplitConfig())
    assert [e["event_id"] for e in train] == ["a"]
    assert [e["event_id"] for e in calib] == ["b"]
    assert [e["event_id"] for e in test] == ["c"]


def test_splits_custom_boundary():
    events = [{"event_id": "a", "date": "2021-12-31"}, {"event_id": "b", "date": "2022-01-01"}]
    cfg = SplitConfig(train_end="2022-01-01", calibration_end="2023-01-01")
    train, calib, _ = split_events(events, cfg)
    assert [e["event_id"] for e in train] == ["a"]
    assert [e["event_id"] for e in calib] == ["b"]


# ---------- baselines ----------

def test_baselines_return_valid_shape():
    event = {
        "event_id": "test_event",
        "commodity": "gold",
        "news_text": "OPEC announced a surprise production cut of 1M bpd.",
    }
    for name in BASELINES:
        preds = run_baseline(name, [event])
        assert len(preds) == 1
        p = preds[0]
        assert p["event_id"] == "test_event"
        assert p["direction"] in ("bullish", "bearish", "neutral")
        assert 0.0 <= p["confidence"] <= 1.0
        assert p["source"] == f"baseline:{name}"


def test_keyword_baseline_recognizes_bullish_language():
    event = {"event_id": "e", "commodity": "crude_oil_wti",
             "news_text": "OPEC production cut, sanctions on major supplier; supply disruption risk."}
    preds = run_baseline("keyword", [event])
    assert preds[0]["direction"] == "bullish"
    assert preds[0]["confidence"] > 0.5


def test_keyword_baseline_recognizes_bearish_language():
    event = {"event_id": "e", "commodity": "crude_oil_wti",
             "news_text": "US SPR release adds supply; demand destruction on recession fears."}
    preds = run_baseline("keyword", [event])
    assert preds[0]["direction"] == "bearish"


def test_random_baseline_is_deterministic_per_event():
    event = {"event_id": "same_id", "commodity": "gold", "news_text": "any"}
    p1 = run_baseline("random", [event])[0]
    p2 = run_baseline("random", [event])[0]
    assert p1["direction"] == p2["direction"]


def test_always_bullish_baseline():
    event = {"event_id": "e", "commodity": "gold", "news_text": "anything"}
    p = run_baseline("always_bullish", [event])[0]
    assert p["direction"] == "bullish"


def test_unknown_baseline_raises():
    with pytest.raises(ValueError, match="Unknown baseline"):
        run_baseline("nonsense", [])


# ---------- grade ----------

def test_derive_actual_direction():
    assert derive_actual_direction(100.0, 102.0) == "bullish"
    assert derive_actual_direction(100.0, 98.0) == "bearish"
    assert derive_actual_direction(100.0, 100.2) == "neutral"  # below threshold
    assert derive_actual_direction(0.0, 50.0) == "neutral"  # invalid input


def test_grade_joins_by_event_id_and_computes_correctness():
    events = [{
        "event_id": "e1",
        "commodity": "gold",
        "date": "2023-01-01",
        "expected_direction": "bullish",
        "prices": {"d0": 100.0, "d1": 102.0, "d3": 105.0, "d7": 108.0, "d14": 110.0, "d30": 95.0},
    }]
    preds = [{"event_id": "e1", "commodity": "gold", "direction": "bullish", "confidence": 0.7}]
    graded = grade(preds, events)
    g = graded[0]
    assert g["correct_label"] is True
    assert g["correct_market_d1"] is True
    assert g["correct_market_d30"] is False  # market dropped at d30
    assert g["return_d7"] == pytest.approx(8.0)


def test_grade_ignores_predictions_without_matching_event():
    events = [{"event_id": "e1", "commodity": "gold", "prices": {"d0": 100.0}, "expected_direction": "bullish"}]
    preds = [{"event_id": "unknown", "direction": "bullish"}]
    assert grade(preds, events) == []


# ---------- statistics ----------

def test_accuracy():
    assert accuracy([1.0, 1.0, 0.0, 0.0]) == 0.5
    assert accuracy([]) == 0.0


def test_bootstrap_ci_reasonable():
    values = [1.0] * 90 + [0.0] * 10  # 90% accuracy
    point, lo, hi = bootstrap_ci(values, accuracy, n_iter=500)
    assert point == pytest.approx(0.9)
    assert lo < point < hi
    assert 0.80 < lo < 0.95
    assert 0.85 < hi <= 1.0


def test_binomial_pvalue_extreme_succes_is_significant():
    # 90 successes out of 100, p=0.33 -> highly significant
    p = binomial_two_sided_pvalue(90, 100, 0.33)
    assert p < 0.001


def test_binomial_pvalue_at_expected_is_one():
    p = binomial_two_sided_pvalue(33, 100, 0.33)
    assert p > 0.8


def test_mcnemar_small_sample_uses_exact():
    # 10 events: 3 both right, 4 A only, 1 B only, 2 both wrong
    p = mcnemar_pvalue(3, 4, 1, 2)
    assert 0.0 < p < 1.0


def test_mcnemar_large_sample_uses_chi2():
    p = mcnemar_pvalue(50, 30, 10, 10)  # 30 vs 10, n=40
    assert p < 0.05  # significant difference


def test_confusion_matrix():
    preds = [
        {"direction": "bullish", "expected_direction": "bullish"},
        {"direction": "bearish", "expected_direction": "bullish"},
        {"direction": "neutral", "expected_direction": "neutral"},
    ]
    cm = confusion_matrix(preds)
    assert cm["bullish"]["bullish"] == 1
    assert cm["bullish"]["bearish"] == 1
    assert cm["neutral"]["neutral"] == 1


# ---------- calibration ----------

def test_fit_calibration_and_ece():
    # Construct predictions where confidence is a rough proxy for correctness
    preds = []
    for _ in range(20):
        preds.append({"direction": "bullish", "expected_direction": "bullish", "confidence": 0.85})
    for _ in range(20):
        preds.append({"direction": "bullish", "expected_direction": "bearish", "confidence": 0.85})
    # At 0.85 confidence, actual accuracy = 50%
    cal = fit_calibration(preds)
    bin_85 = [b for b in cal["bins"] if b["bin_low"] == 0.8][0]
    assert bin_85["count"] == 40
    assert bin_85["empirical_accuracy"] == pytest.approx(0.5)
    ece = expected_calibration_error(cal)
    assert ece > 0.3  # overconfident = large ECE


def test_apply_calibration_remaps_confidence():
    # Fit on data where bin 0.8 has empirical accuracy 0.5
    fit_data = ([{"direction": "b", "expected_direction": "b", "confidence": 0.85}] * 5 +
                [{"direction": "b", "expected_direction": "x", "confidence": 0.85}] * 5)
    cal = fit_calibration(fit_data)
    test_pred = [{"direction": "b", "expected_direction": "b", "confidence": 0.85}]
    mapped = apply_calibration(test_pred, cal)
    assert mapped[0]["calibrated_confidence"] == pytest.approx(0.5)


# ---------- pnl ----------

def test_trade_return_log_direction():
    assert trade_return("bullish", 100.0, 110.0) == pytest.approx(0.0953, abs=1e-3)
    assert trade_return("bearish", 100.0, 110.0) == pytest.approx(-0.0953, abs=1e-3)
    assert trade_return("neutral", 100.0, 110.0) == 0.0


def test_simulate_basic_pnl():
    events = [
        {"event_id": "e1", "commodity": "gold", "prices": {"d0": 100.0, "d7": 110.0}},
        {"event_id": "e2", "commodity": "gold", "prices": {"d0": 100.0, "d7": 95.0}},
    ]
    preds = [
        {"event_id": "e1", "direction": "bullish", "confidence": 0.7},
        {"event_id": "e2", "direction": "bearish", "confidence": 0.7},
    ]
    sim = simulate(preds, events, horizon=7, threshold=0.6)
    assert sim["trades"] == 2
    assert sim["total_return"] > 0  # both trades should be profitable
    assert sim["win_rate"] == 1.0


def test_simulate_filters_by_threshold():
    events = [{"event_id": "e1", "commodity": "gold", "prices": {"d0": 100.0, "d7": 110.0}}]
    preds = [{"event_id": "e1", "direction": "bullish", "confidence": 0.4}]
    sim = simulate(preds, events, horizon=7, threshold=0.6)
    assert sim["trades"] == 0


def test_simulate_ignores_neutral():
    events = [{"event_id": "e1", "commodity": "gold", "prices": {"d0": 100.0, "d7": 110.0}}]
    preds = [{"event_id": "e1", "direction": "neutral", "confidence": 0.9}]
    sim = simulate(preds, events, horizon=7, threshold=0.6)
    assert sim["trades"] == 0
