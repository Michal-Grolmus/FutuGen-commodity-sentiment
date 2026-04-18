"""Enrich evaluation/historical_events.json with multi-horizon prices.

For each event, fetches Yahoo Finance closing price on:
  - d0   = trading day of the event (or next available)
  - d1   = 1 trading day after
  - d3   = 3 trading days after
  - d7   = 7 trading days after
  - d14  = 14 trading days after
  - d30  = 30 trading days after

Output: evaluation/historical_events_enriched.json

Usage: python -m evaluation.fetch_prices
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
EVENTS_PATH = ROOT / "evaluation" / "historical_events.json"
OUT_PATH = ROOT / "evaluation" / "historical_events_enriched.json"

TICKERS = {
    "crude_oil_wti": "CL=F",
    "crude_oil_brent": "BZ=F",
    "natural_gas": "NG=F",
    "gold": "GC=F",
    "silver": "SI=F",
    "wheat": "ZW=F",
    "corn": "ZC=F",
    "copper": "HG=F",
}

HORIZONS = [0, 1, 3, 7, 14, 30]  # trading days after event


def fetch_history(ticker: str, start: str, end: str) -> dict[str, float]:
    """Fetch daily closes between [start, end]. Returns {YYYY-MM-DD: close}."""
    try:
        data = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
        if data.empty:
            return {}
        return {str(idx.date()): float(row["Close"]) for idx, row in data.iterrows()}
    except Exception as e:
        print(f"  WARN: yfinance failed for {ticker}: {e}", file=sys.stderr)
        return {}


def price_at_trading_day_offset(
    prices: dict[str, float],
    event_date: str,
    offset: int,
) -> tuple[str, float] | None:
    """Find the (offset-th) trading day at or after event_date.

    offset=0 returns event day (or next available). offset=1 returns 1 trading day after, etc.
    """
    sorted_dates = sorted(prices.keys())
    # First, find index of first trading day >= event_date
    start_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= event_date:
            start_idx = i
            break
    if start_idx is None:
        return None
    target_idx = start_idx + offset
    if target_idx >= len(sorted_dates):
        return None
    d = sorted_dates[target_idx]
    return d, prices[d]


def enrich_event(event: dict, prices_by_ticker: dict[str, dict[str, float]]) -> dict:
    """Add multi-horizon `prices` field to event."""
    ticker = TICKERS.get(event["commodity"])
    if not ticker:
        event["prices"] = {"error": f"no ticker for {event['commodity']}"}
        return event

    ticker_prices = prices_by_ticker.get(ticker, {})
    out: dict[str, object] = {}
    for h in HORIZONS:
        p = price_at_trading_day_offset(ticker_prices, event["date"], h)
        if p is None:
            out[f"d{h}"] = None
            out[f"d{h}_date"] = None
        else:
            date_str, price = p
            out[f"d{h}"] = round(price, 4)
            out[f"d{h}_date"] = date_str
    event["prices"] = out
    return event


def main() -> None:
    with open(EVENTS_PATH, encoding="utf-8") as f:
        events = json.load(f)
    print(f"Loaded {len(events)} events.")

    # Determine global date range per ticker for one yfinance call per ticker
    by_ticker: dict[str, list[dict]] = {}
    for ev in events:
        t = TICKERS.get(ev["commodity"])
        if t:
            by_ticker.setdefault(t, []).append(ev)

    prices_by_ticker: dict[str, dict[str, float]] = {}
    for ticker, ticker_events in by_ticker.items():
        dates = [ev["date"] for ev in ticker_events]
        earliest = min(dates)
        latest_dt = max(datetime.fromisoformat(d) for d in dates)
        end_date = (latest_dt + timedelta(days=50)).strftime("%Y-%m-%d")
        print(f"Fetching {ticker} from {earliest} to {end_date} "
              f"({len(ticker_events)} events)...")
        prices_by_ticker[ticker] = fetch_history(ticker, earliest, end_date)
        print(f"  Got {len(prices_by_ticker[ticker])} trading days.")

    enriched: list[dict] = []
    missing = 0
    for ev in events:
        enriched_ev = enrich_event(dict(ev), prices_by_ticker)
        if enriched_ev.get("prices", {}).get("d0") is None:
            missing += 1
        enriched.append(enriched_ev)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(enriched)} enriched events to {OUT_PATH.relative_to(ROOT)}")
    if missing:
        print(f"WARNING: {missing} events had no price data.")


if __name__ == "__main__":
    main()
