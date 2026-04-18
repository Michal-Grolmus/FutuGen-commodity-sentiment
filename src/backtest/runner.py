"""Background task that checks due backtests every 5 minutes.

For each pending signal whose backtest_at has passed:
- Fetches current Yahoo Finance price
- Compares to price_snapshot at signal time
- Computes direction match and change percentage
- Writes result back to log
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from functools import partial
from typing import Any

from src.backtest import signal_log
from src.prices.yahoo_client import PriceClient

logger = logging.getLogger(__name__)

CHECK_INTERVAL_S = 300  # run every 5 minutes
# Threshold for calling a movement "bullish" / "bearish" vs "neutral"
NEUTRAL_THRESHOLD_PCT = 0.5


def _evaluate_entry(entry: dict[str, Any], client: PriceClient) -> dict[str, Any] | None:
    commodity = entry["commodity"]
    price_then = entry.get("price_snapshot")
    if price_then is None:
        return {
            "checked_at": datetime.now(UTC).isoformat(),
            "error": "no price snapshot at signal time",
            "correct": None,
        }
    price_now = client.get_current_price(commodity)
    if price_now is None:
        return None  # skip this cycle — retry later

    change_pct = (price_now - price_then) / price_then * 100
    if change_pct > NEUTRAL_THRESHOLD_PCT:
        actual = "bullish"
    elif change_pct < -NEUTRAL_THRESHOLD_PCT:
        actual = "bearish"
    else:
        actual = "neutral"

    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "price_then": price_then,
        "price_now": price_now,
        "change_pct": round(change_pct, 3),
        "actual_direction": actual,
        "correct": actual == entry["direction"],
    }


async def run_once() -> int:
    """Run one pass of backtesting. Returns count of signals evaluated."""
    pending = signal_log.pending_backtests()
    if not pending:
        return 0

    loop = asyncio.get_running_loop()
    client = PriceClient()
    evaluated = 0

    for entry in pending:
        # Yahoo Finance call is blocking — run in executor
        result = await loop.run_in_executor(None, partial(_evaluate_entry, entry, client))
        if result is None:
            continue  # price unavailable, retry next cycle
        if signal_log.update_result(entry["id"], result):
            evaluated += 1
            logger.info(
                "Backtest %s (%s/%s): predicted=%s actual=%s correct=%s change=%s%%",
                entry["id"], entry["commodity"], entry["timeframe"],
                entry["direction"], result.get("actual_direction"),
                result.get("correct"), result.get("change_pct"),
            )

    return evaluated


async def run_loop(stop_event: asyncio.Event | None = None) -> None:
    """Run indefinitely, checking every CHECK_INTERVAL_S."""
    logger.info("Backtest runner started (interval=%ds)", CHECK_INTERVAL_S)
    while True:
        if stop_event and stop_event.is_set():
            break
        try:
            count = await run_once()
            if count > 0:
                logger.info("Backtest cycle: evaluated %d signals", count)
        except Exception:
            logger.exception("Backtest runner error")
        try:
            await asyncio.wait_for(
                stop_event.wait() if stop_event else asyncio.sleep(CHECK_INTERVAL_S),
                timeout=CHECK_INTERVAL_S,
            )
        except TimeoutError:
            pass
        except Exception:
            pass
    logger.info("Backtest runner stopped.")
