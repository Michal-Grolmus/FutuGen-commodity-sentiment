"""Append-only JSONL signal log for delayed backtesting.

Each signal gets:
- Price snapshot from Yahoo Finance at generation time
- Scheduled backtest_at timestamp based on timeframe (short=+24h, medium=+7d)
- backtest_result populated later by the runner

Log file: data/signals_log.jsonl (one JSON object per line)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.models import CommoditySignal, Timeframe

logger = logging.getLogger(__name__)

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "signals_log.jsonl"

# How long to wait before backtesting, per timeframe
BACKTEST_DELAY: dict[Timeframe, timedelta] = {
    Timeframe.SHORT_TERM: timedelta(hours=24),
    Timeframe.MEDIUM_TERM: timedelta(days=7),
}

# Single lock for append/read to avoid interleaving across threads
_lock = threading.Lock()


def _ensure_dir() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def append(
    signal: CommoditySignal,
    *,
    stream_id: str,
    chunk_id: str,
    price_snapshot: float | None,
) -> str:
    """Record a signal with price snapshot. Returns the log entry id."""
    _ensure_dir()
    now = datetime.now(UTC)
    entry_id = f"{now.strftime('%Y%m%d%H%M%S')}_{signal.commodity}_{chunk_id}"
    backtest_at = now + BACKTEST_DELAY.get(signal.timeframe, timedelta(hours=24))

    entry: dict[str, Any] = {
        "id": entry_id,
        "timestamp": now.isoformat(),
        "stream_id": stream_id,
        "chunk_id": chunk_id,
        "commodity": signal.commodity,
        "display_name": signal.display_name,
        "direction": signal.direction.value,
        "confidence": signal.confidence,
        "rationale": signal.rationale,
        "timeframe": signal.timeframe.value,
        "source_text": signal.source_text,
        "price_snapshot": price_snapshot,
        "backtest_at": backtest_at.isoformat(),
        "backtest_result": None,
    }

    with _lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.debug("Logged signal %s for backtest at %s", entry_id, backtest_at.isoformat())
    return entry_id


def read_all() -> list[dict[str, Any]]:
    """Read the full log. For small files only."""
    _ensure_dir()
    if not LOG_PATH.exists():
        return []
    entries = []
    with _lock:
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def pending_backtests(now: datetime | None = None) -> list[dict[str, Any]]:
    """Return entries whose backtest_at is due and haven't been processed yet."""
    now = now or datetime.now(UTC)
    out = []
    for entry in read_all():
        if entry.get("backtest_result") is not None:
            continue
        try:
            due = datetime.fromisoformat(entry["backtest_at"])
        except (KeyError, ValueError):
            continue
        if due <= now:
            out.append(entry)
    return out


def update_result(entry_id: str, result: dict[str, Any]) -> bool:
    """Rewrite the log with backtest_result filled in for a specific entry."""
    _ensure_dir()
    if not LOG_PATH.exists():
        return False
    updated = False
    with _lock:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
        new_lines = []
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                new_lines.append(line)
                continue
            if entry.get("id") == entry_id:
                entry["backtest_result"] = result
                updated = True
            new_lines.append(json.dumps(entry, ensure_ascii=False))
        if updated:
            LOG_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updated


def compute_stats() -> dict[str, Any]:
    """Aggregate accuracy stats from completed backtests, grouped by timeframe."""
    all_entries = read_all()
    total = len(all_entries)
    evaluated = [e for e in all_entries if e.get("backtest_result") is not None]
    pending = total - len(evaluated)

    by_timeframe: dict[str, dict[str, int]] = {
        "short_term": {"total": 0, "correct": 0, "pending": 0},
        "medium_term": {"total": 0, "correct": 0, "pending": 0},
    }

    for e in all_entries:
        tf = e.get("timeframe", "short_term")
        if tf not in by_timeframe:
            continue
        by_timeframe[tf]["total"] += 1
        result = e.get("backtest_result")
        if result is None:
            by_timeframe[tf]["pending"] += 1
        elif result.get("correct"):
            by_timeframe[tf]["correct"] += 1

    # Overall accuracy of evaluated signals (both timeframes combined)
    correct = sum(1 for e in evaluated if e.get("backtest_result", {}).get("correct"))
    accuracy = (correct / len(evaluated)) if evaluated else None

    return {
        "total_signals": total,
        "evaluated": len(evaluated),
        "pending": pending,
        "accuracy": accuracy,
        "by_timeframe": by_timeframe,
    }
