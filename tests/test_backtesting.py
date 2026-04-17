"""Tests for backtesting module."""
from __future__ import annotations

from evaluation.backtesting import format_backtest_report
from src.models import CommoditySignal, Direction, Timeframe


def _make_signal(commodity: str, direction: Direction) -> CommoditySignal:
    return CommoditySignal(
        commodity=commodity,
        display_name=commodity.replace("_", " ").title(),
        direction=direction,
        confidence=0.8,
        rationale="Test",
        timeframe=Timeframe.SHORT_TERM,
        source_text="test",
    )


def test_format_backtest_report_with_results():
    results = [
        {
            "commodity": "crude_oil_wti",
            "predicted_direction": "bullish",
            "actual_direction": "bullish",
            "price_before": 70.0,
            "price_after": 72.5,
            "change_pct": 3.57,
            "correct": True,
            "confidence": 0.85,
        },
        {
            "commodity": "gold",
            "predicted_direction": "bearish",
            "actual_direction": "bullish",
            "price_before": 2000.0,
            "price_after": 2030.0,
            "change_pct": 1.5,
            "correct": False,
            "confidence": 0.7,
        },
    ]
    report = format_backtest_report(results)
    assert "## Backtesting Results" in report
    assert "1/2" in report or "50%" in report
    assert "crude_oil_wti" in report
    assert "gold" in report


def test_format_backtest_report_empty():
    report = format_backtest_report([])
    assert "No backtesting data" in report


def test_format_backtest_report_all_correct():
    results = [
        {
            "commodity": "copper",
            "predicted_direction": "bullish",
            "actual_direction": "bullish",
            "price_before": 4.0,
            "price_after": 4.2,
            "change_pct": 5.0,
            "correct": True,
            "confidence": 0.8,
        },
    ]
    report = format_backtest_report(results)
    assert "1/1" in report
    assert "100%" in report
