"""Tests for persistent signal log + backtest stats."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.backtest import signal_log
from src.models import CommoditySignal, Direction, Timeframe


def _make_signal(commodity: str = "gold", direction: Direction = Direction.BULLISH,
                 confidence: float = 0.8, timeframe: Timeframe = Timeframe.SHORT_TERM) -> CommoditySignal:
    return CommoditySignal(
        commodity=commodity, display_name=commodity.title(),
        direction=direction, confidence=confidence,
        rationale="test", timeframe=timeframe, source_text="test",
    )


@pytest.fixture
def temp_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log_path = tmp_path / "signals_log.jsonl"
    monkeypatch.setattr(signal_log, "LOG_PATH", log_path)
    return log_path


def test_append_and_read(temp_log: Path):
    signal_log.append(_make_signal(), stream_id="s1", chunk_id="c1", price_snapshot=100.0)
    entries = signal_log.read_all()
    assert len(entries) == 1
    assert entries[0]["commodity"] == "gold"
    assert entries[0]["price_snapshot"] == 100.0
    assert entries[0]["backtest_result"] is None


def test_backtest_delay_short_vs_medium(temp_log: Path):
    signal_log.append(_make_signal(timeframe=Timeframe.SHORT_TERM),
                      stream_id="s1", chunk_id="c1", price_snapshot=100.0)
    signal_log.append(_make_signal(timeframe=Timeframe.MEDIUM_TERM),
                      stream_id="s1", chunk_id="c2", price_snapshot=100.0)
    entries = signal_log.read_all()

    now = datetime.now(UTC)
    short_due = datetime.fromisoformat(entries[0]["backtest_at"])
    medium_due = datetime.fromisoformat(entries[1]["backtest_at"])

    # short_term ~ +24h, medium_term ~ +7d
    assert abs((short_due - now).total_seconds() - 86400) < 60
    assert abs((medium_due - now).total_seconds() - 604800) < 60


def test_pending_backtests_respects_due_time(temp_log: Path):
    signal_log.append(_make_signal(), stream_id="s1", chunk_id="c1", price_snapshot=100.0)
    # Now: none due yet
    assert len(signal_log.pending_backtests()) == 0
    # Future "now" = entry is due
    future = datetime.now(UTC) + timedelta(days=2)
    assert len(signal_log.pending_backtests(now=future)) == 1


def test_update_result(temp_log: Path):
    signal_log.append(_make_signal(), stream_id="s1", chunk_id="c1", price_snapshot=100.0)
    entry_id = signal_log.read_all()[0]["id"]
    result = {"price_then": 100.0, "price_now": 105.0, "change_pct": 5.0,
              "actual_direction": "bullish", "correct": True}
    assert signal_log.update_result(entry_id, result) is True
    entries = signal_log.read_all()
    assert entries[0]["backtest_result"]["correct"] is True


def test_compute_stats(temp_log: Path):
    # 2 short, 1 medium; mark 1 short as evaluated correct, 1 pending
    signal_log.append(_make_signal(timeframe=Timeframe.SHORT_TERM),
                      stream_id="s1", chunk_id="c1", price_snapshot=100.0)
    signal_log.append(_make_signal(timeframe=Timeframe.SHORT_TERM),
                      stream_id="s1", chunk_id="c2", price_snapshot=100.0)
    signal_log.append(_make_signal(timeframe=Timeframe.MEDIUM_TERM),
                      stream_id="s1", chunk_id="c3", price_snapshot=100.0)
    entries = signal_log.read_all()
    signal_log.update_result(entries[0]["id"], {"correct": True})

    stats = signal_log.compute_stats()
    assert stats["total_signals"] == 3
    assert stats["evaluated"] == 1
    assert stats["pending"] == 2
    assert stats["by_timeframe"]["short_term"]["total"] == 2
    assert stats["by_timeframe"]["short_term"]["correct"] == 1
    assert stats["by_timeframe"]["medium_term"]["total"] == 1
    assert stats["accuracy"] == 1.0
