from __future__ import annotations

from evaluation.dataset import compute_metrics, evaluate_prediction
from src.models import CommoditySignal, Direction, GroundTruthLabel, Timeframe


def _make_signal(commodity: str, direction: Direction, confidence: float = 0.8) -> CommoditySignal:
    return CommoditySignal(
        commodity=commodity,
        display_name=commodity.replace("_", " ").title(),
        direction=direction,
        confidence=confidence,
        rationale="Test rationale",
        timeframe=Timeframe.SHORT_TERM,
        source_text="test",
    )


def _make_gt(
    excerpt_id: str,
    commodities: list[str],
    direction: Direction,
) -> GroundTruthLabel:
    return GroundTruthLabel(
        excerpt_id=excerpt_id,
        audio_file="test.wav",
        description="Test",
        transcript_text="Test transcript",
        expected_commodities=commodities,
        expected_direction=direction,
        expected_timeframe=Timeframe.SHORT_TERM,
        rationale="Test",
    )


def test_correct_prediction():
    gt = _make_gt("test_01", ["crude_oil_wti"], Direction.BULLISH)
    signals = [_make_signal("crude_oil_wti", Direction.BULLISH)]
    pred = evaluate_prediction(signals, gt)
    assert pred.direction_correct is True
    assert pred.commodity_recall == 1.0


def test_wrong_direction():
    gt = _make_gt("test_02", ["gold"], Direction.BEARISH)
    signals = [_make_signal("gold", Direction.BULLISH)]
    pred = evaluate_prediction(signals, gt)
    assert pred.direction_correct is False
    assert pred.commodity_recall == 1.0


def test_no_signals_neutral():
    gt = _make_gt("test_03", [], Direction.NEUTRAL)
    pred = evaluate_prediction([], gt)
    assert pred.direction_correct is True
    assert pred.commodity_recall == 1.0


def test_partial_commodity_recall():
    gt = _make_gt("test_04", ["crude_oil_wti", "crude_oil_brent"], Direction.BULLISH)
    signals = [_make_signal("crude_oil_wti", Direction.BULLISH)]
    pred = evaluate_prediction(signals, gt)
    assert pred.direction_correct is True
    assert pred.commodity_recall == 0.5


def test_compute_metrics():
    gt1 = _make_gt("t1", ["gold"], Direction.BULLISH)
    gt2 = _make_gt("t2", ["copper"], Direction.BEARISH)

    pred1 = evaluate_prediction([_make_signal("gold", Direction.BULLISH)], gt1)
    pred2 = evaluate_prediction([_make_signal("copper", Direction.BULLISH)], gt2)  # wrong

    metrics = compute_metrics([pred1, pred2])
    assert metrics["direction_accuracy"] == 0.5
    assert metrics["total_excerpts"] == 2
    assert len(metrics["errors"]) == 1
