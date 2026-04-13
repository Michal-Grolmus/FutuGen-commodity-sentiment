"""Backtesting: compare generated signals against historical price movements."""
from __future__ import annotations

import logging

from src.models import CommoditySignal, Direction
from src.prices.yahoo_client import COMMODITY_TICKERS, PriceClient

logger = logging.getLogger(__name__)


def backtest_signal(
    signal: CommoditySignal,
    price_client: PriceClient,
    hours_ahead: int = 24,
) -> dict[str, object] | None:
    """Check if a signal's direction matched actual price movement.

    Returns a dict with actual price change and whether the signal was correct,
    or None if price data is unavailable.
    """
    if signal.commodity not in COMMODITY_TICKERS:
        return None

    try:
        import yfinance as yf

        ticker_symbol = COMMODITY_TICKERS[signal.commodity]
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period="5d", interval="1h")

        if len(hist) < 2:
            return None

        price_before = float(hist["Close"].iloc[0])
        # Look at price 'hours_ahead' later (or last available)
        lookahead_idx = min(hours_ahead, len(hist) - 1)
        price_after = float(hist["Close"].iloc[lookahead_idx])
        change_pct = (price_after - price_before) / price_before * 100

        actual_direction = Direction.BULLISH if change_pct > 0.1 else (
            Direction.BEARISH if change_pct < -0.1 else Direction.NEUTRAL
        )

        return {
            "commodity": signal.commodity,
            "predicted_direction": signal.direction.value,
            "actual_direction": actual_direction.value,
            "price_before": price_before,
            "price_after": price_after,
            "change_pct": change_pct,
            "correct": signal.direction == actual_direction,
            "confidence": signal.confidence,
        }
    except Exception:
        logger.exception("Backtesting failed for %s", signal.commodity)
        return None


def backtest_signals(
    signals: list[CommoditySignal],
    price_client: PriceClient | None = None,
) -> list[dict[str, object]]:
    """Backtest a batch of signals against recent price data."""
    if price_client is None:
        price_client = PriceClient()

    results = []
    for signal in signals:
        result = backtest_signal(signal, price_client)
        if result is not None:
            results.append(result)

    return results


def format_backtest_report(results: list[dict[str, object]]) -> str:
    """Format backtesting results as markdown."""
    if not results:
        return "No backtesting data available.\n"

    correct = sum(1 for r in results if r["correct"])
    total = len(results)
    accuracy = correct / total * 100 if total > 0 else 0

    lines = [
        "## Backtesting Results",
        "",
        f"- **Signals tested**: {total}",
        f"- **Correct direction**: {correct}/{total} ({accuracy:.0f}%)",
        "",
        "| Commodity | Predicted | Actual | Price Change | Correct |",
        "|-----------|-----------|--------|-------------|---------|",
    ]

    for r in results:
        check = "Y" if r["correct"] else "N"
        lines.append(
            f"| {r['commodity']} | {r['predicted_direction']} | {r['actual_direction']} "
            f"| {r['change_pct']:+.2f}% | {check} |"
        )

    return "\n".join(lines) + "\n"
