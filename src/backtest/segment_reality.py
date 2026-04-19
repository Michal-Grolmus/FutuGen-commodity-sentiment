"""Post-close reality scoring for segments.

When a segment closes, we schedule price lookups at multiple horizons
(+1 min, +5 min, +15 min, +1 h) for the primary commodity. Once each
horizon's deadline has passed, fetch the price and grade whether the
segment's direction was right.

Runs as a single async task started by the pipeline. Reads pending work
from a module-level queue (fed by SegmentAggregator close events).

For Yahoo Finance, the shortest available interval is 1-minute bars
(past 7 days only). For longer horizons we fall back to current close.
This is explicitly documented — true intraday validation needs a paid
data source (Polygon, Alpha Vantage Premium), but this gives a directional
signal already.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import yfinance as yf

from src.backtest import segment_log
from src.models import Direction, Segment
from src.prices.yahoo_client import COMMODITY_TICKERS

logger = logging.getLogger(__name__)

# Horizons to score at (seconds after segment close)
HORIZONS_SECONDS = {
    "h1m": 60,
    "h5m": 300,
    "h15m": 900,
    "h1h": 3600,
}

NEUTRAL_THRESHOLD_PCT = 0.5


async def _fetch_price_at(ticker: str, target_time: datetime) -> float | None:
    """Fetch the closing price closest to (but not after) target_time.

    For target_time within past 7 days: uses 1m interval bars.
    Otherwise: falls back to daily close on that day.
    """
    now = datetime.now(UTC)
    age_days = (now - target_time).total_seconds() / 86400.0
    try:
        if age_days <= 6.5:
            # Use 1m bars for past week — most granular free option
            hist = await asyncio.to_thread(
                yf.Ticker(ticker).history,
                period="7d", interval="1m",
            )
        else:
            hist = await asyncio.to_thread(
                yf.Ticker(ticker).history,
                start=target_time.strftime("%Y-%m-%d"),
                end=(target_time + timedelta(days=2)).strftime("%Y-%m-%d"),
                interval="1d",
            )
        if hist is None or hist.empty:
            return None
        # Find last row whose index <= target_time
        target_naive = target_time.replace(tzinfo=None)
        # yfinance index may be tz-aware; normalize
        if hasattr(hist.index, "tz") and hist.index.tz is not None:
            target_naive = target_time.astimezone(hist.index.tz).replace(tzinfo=None)
            idx_naive = hist.index.tz_localize(None)
        else:
            idx_naive = hist.index
        mask = idx_naive <= target_naive
        eligible = hist[mask]
        if eligible.empty:
            # Market hasn't opened yet for target_time — use first available
            return float(hist["Close"].iloc[0])
        return float(eligible["Close"].iloc[-1])
    except Exception:
        logger.exception("Failed to fetch price for %s at %s", ticker, target_time)
        return None


def _derive_direction(price_then: float, price_now: float) -> str:
    if price_then <= 0:
        return "neutral"
    pct = (price_now - price_then) / price_then * 100.0
    if abs(pct) < NEUTRAL_THRESHOLD_PCT:
        return "neutral"
    return "bullish" if pct > 0 else "bearish"


async def score_segment(segment: Segment) -> dict[str, Any]:
    """Compute reality_score dict for a closed segment. Waits for the longest
    horizon to elapse before returning."""
    ticker = COMMODITY_TICKERS.get(segment.primary_commodity)
    if ticker is None or segment.end_time is None:
        return {"error": f"no ticker for {segment.primary_commodity}"}

    # Price at segment close
    price_t0 = await _fetch_price_at(ticker, segment.end_time)
    result: dict[str, Any] = {
        "ticker": ticker,
        "end_time": segment.end_time.isoformat(),
        "price_t0": price_t0,
        "predicted_direction": segment.direction.value,
    }

    # Wait out each horizon, then fetch price + grade
    for label, offset_s in HORIZONS_SECONDS.items():
        target = segment.end_time + timedelta(seconds=offset_s)
        # Sleep just long enough that target time is in the past
        sleep_s = max(0.0, (target - datetime.now(UTC)).total_seconds() + 5.0)
        if sleep_s > 0:
            await asyncio.sleep(sleep_s)
        price_h = await _fetch_price_at(ticker, target)
        result[f"price_{label}"] = price_h
        if price_h is not None and price_t0 is not None:
            actual = _derive_direction(price_t0, price_h)
            result[f"actual_direction_{label}"] = actual
            # Segment direction may be 'neutral'; grading is straightforward match
            if segment.direction == Direction.NEUTRAL:
                correct = actual == "neutral"
            else:
                correct = actual == segment.direction.value
            result[f"correct_{label}"] = correct
        else:
            result[f"actual_direction_{label}"] = None
            result[f"correct_{label}"] = None
    return result


# ----------------------------------------------------------------------
# Async worker — fed by pipeline via enqueue()
# ----------------------------------------------------------------------
_queue: asyncio.Queue[Segment] | None = None


def enqueue(segment: Segment) -> None:
    """Called from pipeline broadcast loop after a segment closes."""
    global _queue  # noqa: PLW0603
    if _queue is None:
        # Best-effort: may be called before worker is running
        return
    try:
        _queue.put_nowait(segment)
    except asyncio.QueueFull:
        logger.warning("Reality score queue full; dropping segment %s",
                       segment.segment_id)


async def run_worker() -> None:
    """Long-running task. Pops segments off the queue and scores them."""
    global _queue  # noqa: PLW0603
    if _queue is None:
        _queue = asyncio.Queue(maxsize=200)
    logger.info("Segment reality worker started.")
    while True:
        try:
            segment = await _queue.get()
        except asyncio.CancelledError:
            logger.info("Segment reality worker cancelled.")
            raise
        try:
            score = await score_segment(segment)
            segment_log.update_reality_score(segment.segment_id, score)
            logger.info(
                "Scored segment %s (%s): %s",
                segment.segment_id, segment.primary_commodity,
                {k: v for k, v in score.items() if k.startswith("correct_")},
            )
        except Exception:
            logger.exception("Failed to score segment %s", segment.segment_id)


def ensure_queue() -> asyncio.Queue[Segment]:
    """Initialize queue on first access inside an async context."""
    global _queue  # noqa: PLW0603
    if _queue is None:
        _queue = asyncio.Queue(maxsize=200)
    return _queue


async def stop_worker_gracefully(worker_task: asyncio.Task[None]) -> None:
    """Cancel worker and wait briefly for clean exit."""
    worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(worker_task, timeout=3.0)
