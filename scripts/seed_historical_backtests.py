"""Seed data/signals_log.jsonl with historical commodity events.

For each curated historical event:
1. Predicts direction based on event context (what an analyst would have said
   AT THE TIME, not knowing the outcome).
2. Fetches actual Yahoo Finance closing price on the event date (price_then).
3. Fetches closing price N trading days later based on timeframe:
   - short_term: 1 trading day after
   - medium_term: 5 trading days after
4. Computes actual direction and correctness.
5. Writes fully populated backtest entry to the log.

Result: the dashboard's Backtest widget shows real accuracy from day 1.

Usage: python scripts/seed_historical_backtests.py
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "data" / "signals_log.jsonl"
NEUTRAL_THRESHOLD_PCT = 0.5

# Yahoo Finance tickers
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

# Curated historical events. direction = prediction an analyst WOULD have made
# at the time based on the event context, without knowing the outcome.
HISTORICAL_EVENTS = [
    # --- 2022 ---
    {
        "date": "2022-02-24", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.88, "timeframe": "short_term",
        "rationale": "Russia invades Ukraine; major energy exporter, sanctions imminent, supply disruption risk.",
        "source_text": "Russian military forces have launched a full-scale invasion of Ukraine this morning.",
        "event_name": "russia_invades_ukraine",
    },
    {
        "date": "2022-02-24", "commodity": "wheat",
        "direction": "bullish", "confidence": 0.85, "timeframe": "medium_term",
        "rationale": "Ukraine is top-5 wheat exporter. War disrupts Black Sea shipping for months.",
        "source_text": "Russian military forces have launched a full-scale invasion of Ukraine.",
        "event_name": "russia_invades_ukraine_wheat",
    },
    {
        "date": "2022-02-24", "commodity": "natural_gas",
        "direction": "bullish", "confidence": 0.82, "timeframe": "medium_term",
        "rationale": "Russia supplies 40% of European gas. Sanctions will tighten supply for winter.",
        "source_text": "Russian invasion of Ukraine triggers European energy security concerns.",
        "event_name": "russia_invades_ukraine_gas",
    },
    {
        "date": "2022-10-19", "commodity": "crude_oil_wti",
        "direction": "bearish", "confidence": 0.65, "timeframe": "short_term",
        "rationale": "US announces additional 15M barrel SPR release. Short-term supply increase.",
        "source_text": "The Biden administration announced an additional 15 million barrel "
                       "release from the Strategic Petroleum Reserve.",
        "event_name": "spr_release",
    },
    # --- 2023 ---
    {
        "date": "2023-02-01", "commodity": "gold",
        "direction": "bearish", "confidence": 0.60, "timeframe": "short_term",
        "rationale": "Fed raises rates 25bp. Higher rates increase opportunity cost of holding gold.",
        "source_text": "The Federal Reserve raised its benchmark rate by 25 basis points today.",
        "event_name": "fed_feb2023_hike",
    },
    {
        "date": "2023-04-03", "commodity": "crude_oil_wti",
        "direction": "bullish", "confidence": 0.88, "timeframe": "short_term",
        "rationale": "Surprise OPEC+ production cut of 1.16M bpd starting May. Major supply tightening.",
        "source_text": "OPEC+ announced a voluntary production cut of 1.16 million barrels per day.",
        "event_name": "opec_apr2023_cut",
    },
    {
        "date": "2023-04-03", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.88, "timeframe": "short_term",
        "rationale": "Brent as international benchmark directly affected by OPEC+ supply cut.",
        "source_text": "OPEC+ announced a voluntary production cut of 1.16 million barrels per day.",
        "event_name": "opec_apr2023_cut_brent",
    },
    {
        "date": "2023-05-03", "commodity": "gold",
        "direction": "bearish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Fed raises rates 25bp to 5.25%. Continued hiking cycle pressures non-yielding gold.",
        "source_text": "The Federal Reserve raised rates by another 25 basis points to 5.25 percent.",
        "event_name": "fed_may2023_hike",
    },
    {
        "date": "2023-07-26", "commodity": "gold",
        "direction": "bearish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Fed raises rates 25bp to 5.50%. Restrictive policy stance continues.",
        "source_text": "The Federal Reserve raised rates by 25 basis points to 5.50 percent.",
        "event_name": "fed_jul2023_hike",
    },
    {
        "date": "2023-09-20", "commodity": "gold",
        "direction": "bullish", "confidence": 0.60, "timeframe": "medium_term",
        "rationale": "Fed pauses rate hikes. Dovish signal reduces opportunity cost of holding gold.",
        "source_text": "The Federal Reserve held rates steady, signaling a pause in the tightening cycle.",
        "event_name": "fed_sep2023_pause",
    },
    {
        "date": "2023-10-09", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.75, "timeframe": "short_term",
        "rationale": "Hamas attacks Israel; Middle East geopolitical risk premium spikes.",
        "source_text": "Hamas launched a surprise large-scale attack on Israel from Gaza.",
        "event_name": "israel_hamas_war",
    },
    {
        "date": "2023-11-30", "commodity": "crude_oil_wti",
        "direction": "bullish", "confidence": 0.70, "timeframe": "medium_term",
        "rationale": "OPEC+ extends 2.2M bpd voluntary production cuts into Q1 2024.",
        "source_text": "OPEC+ agreed to extend voluntary production cuts of 2.2 million bpd through Q1 2024.",
        "event_name": "opec_nov2023_extend",
    },
    # --- 2024 ---
    {
        "date": "2024-03-03", "commodity": "crude_oil_wti",
        "direction": "bullish", "confidence": 0.70, "timeframe": "medium_term",
        "rationale": "OPEC+ extends voluntary cuts through Q2 2024. Supply remains restricted.",
        "source_text": "OPEC+ extended voluntary production cuts of 2.2 million bpd through the second quarter.",
        "event_name": "opec_mar2024_extend",
    },
    {
        "date": "2024-04-01", "commodity": "gold",
        "direction": "bullish", "confidence": 0.70, "timeframe": "medium_term",
        "rationale": "Geopolitical tensions in Middle East drive safe-haven demand for gold.",
        "source_text": "Middle East tensions escalate with reported Israeli strike on Iranian consulate in Damascus.",
        "event_name": "iran_tensions_gold",
    },
    {
        "date": "2024-07-31", "commodity": "gold",
        "direction": "bullish", "confidence": 0.65, "timeframe": "short_term",
        "rationale": "Fed signals upcoming rate cuts. Lower real yields support gold.",
        "source_text": "Fed Chair Powell signaled that rate cuts are likely at the next meeting.",
        "event_name": "fed_jul2024_signal",
    },
    {
        "date": "2024-09-18", "commodity": "gold",
        "direction": "bullish", "confidence": 0.80, "timeframe": "short_term",
        "rationale": "Fed cuts rates 50bp, larger than expected. Weaker dollar, lower yields support gold.",
        "source_text": "The Federal Reserve cut its benchmark rate by 50 basis points, a larger-than-expected move.",
        "event_name": "fed_sep2024_cut",
    },
    {
        "date": "2024-11-07", "commodity": "gold",
        "direction": "bearish", "confidence": 0.50, "timeframe": "short_term",
        "rationale": "Post-US-election dollar strength pressures gold near-term. Trump tax/tariff policy expectations.",
        "source_text": "Following the US presidential election, the dollar index surged to multi-month highs.",
        "event_name": "trump_election_gold",
    },
    {
        "date": "2024-12-05", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.55, "timeframe": "medium_term",
        "rationale": "OPEC+ delays planned output increase to April 2025. Continued supply restraint.",
        "source_text": "OPEC+ agreed to delay the planned unwinding of voluntary cuts until April 2025.",
        "event_name": "opec_dec2024_delay",
    },
]


def get_closing_prices(ticker: str, start: str, end: str) -> dict[str, float]:
    """Fetch daily closing prices between start and end. Returns {date_str: close}."""
    try:
        data = yf.Ticker(ticker).history(start=start, end=end)
        if data.empty:
            return {}
        return {str(idx.date()): float(row["Close"]) for idx, row in data.iterrows()}
    except Exception as e:
        print(f"  WARN: yfinance failed for {ticker}: {e}")
        return {}


def find_price_at_or_after(prices: dict[str, float], target_date: str) -> tuple[str, float] | None:
    """Find first trading day >= target_date with a price."""
    sorted_dates = sorted(prices.keys())
    for d in sorted_dates:
        if d >= target_date:
            return d, prices[d]
    return None


def trading_days_after(prices: dict[str, float], start_date: str, n_days: int) -> tuple[str, float] | None:
    """Find the Nth trading day after start_date (inclusive of start counts as 0)."""
    sorted_dates = sorted(prices.keys())
    found_start = False
    count = 0
    for d in sorted_dates:
        if d >= start_date and not found_start:
            found_start = True
            continue
        if found_start:
            count += 1
            if count >= n_days:
                return d, prices[d]
    return None


def backtest_event(event: dict) -> dict | None:
    commodity = event["commodity"]
    ticker = TICKERS.get(commodity)
    if not ticker:
        print(f"  SKIP: no ticker for {commodity}")
        return None

    event_date = event["date"]
    start = event_date
    # Fetch a 20-day window to ensure we have enough trading days after
    end_date = (datetime.strptime(event_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")

    prices = get_closing_prices(ticker, start, end_date)
    if not prices:
        print(f"  SKIP {event['event_name']}: no price data")
        return None

    # price_then: first trading day on/after event date
    then = find_price_at_or_after(prices, event_date)
    if not then:
        print(f"  SKIP {event['event_name']}: no price_then")
        return None
    then_date, price_then = then

    # price_now: 1 trading day later (short) or 5 (medium)
    lag = 1 if event["timeframe"] == "short_term" else 5
    later = trading_days_after(prices, then_date, lag)
    if not later:
        print(f"  SKIP {event['event_name']}: no price_now after +{lag} days")
        return None
    now_date, price_now = later

    change_pct = (price_now - price_then) / price_then * 100
    if change_pct > NEUTRAL_THRESHOLD_PCT:
        actual = "bullish"
    elif change_pct < -NEUTRAL_THRESHOLD_PCT:
        actual = "bearish"
    else:
        actual = "neutral"

    correct = actual == event["direction"]

    # Construct log entry as if the signal was generated on event_date
    event_ts = datetime.strptime(then_date, "%Y-%m-%d").replace(tzinfo=UTC)
    check_ts = datetime.strptime(now_date, "%Y-%m-%d").replace(tzinfo=UTC)

    entry = {
        "id": f"hist_{event['event_name']}",
        "timestamp": event_ts.isoformat(),
        "stream_id": "historical_seed",
        "chunk_id": event["event_name"],
        "commodity": commodity,
        "display_name": commodity.replace("_", " ").title().replace("Wti", "WTI"),
        "direction": event["direction"],
        "confidence": event["confidence"],
        "rationale": event["rationale"],
        "timeframe": event["timeframe"],
        "source_text": event["source_text"],
        "price_snapshot": round(price_then, 3),
        "backtest_at": check_ts.isoformat(),
        "backtest_result": {
            "checked_at": check_ts.isoformat(),
            "price_then": round(price_then, 3),
            "price_now": round(price_now, 3),
            "change_pct": round(change_pct, 3),
            "actual_direction": actual,
            "correct": correct,
        },
    }
    status = "OK" if correct else "WRONG"
    print(f"  [{status}] {event['event_name']}: predicted={event['direction']} "
          f"actual={actual} ({change_pct:+.2f}%) [{event['timeframe']}]")
    return entry


def main() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Read existing log, filter out previous historical seeds (so we can re-run)
    existing: list[dict] = []
    if LOG_PATH.exists():
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    if not e.get("id", "").startswith("hist_"):
                        existing.append(e)
                except json.JSONDecodeError:
                    continue

    print(f"Seeding {len(HISTORICAL_EVENTS)} historical events...")
    seeded = []
    for event in HISTORICAL_EVENTS:
        entry = backtest_event(event)
        if entry:
            seeded.append(entry)

    # Merge: keep non-historical entries + new historical
    all_entries = existing + seeded
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        for e in all_entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    correct = sum(1 for e in seeded if e["backtest_result"]["correct"])
    total = len(seeded)
    print(f"\nSeeded {total} historical backtest entries to {LOG_PATH}")
    print(f"Historical accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
    by_tf: dict[str, list] = {"short_term": [], "medium_term": []}
    for e in seeded:
        by_tf[e["timeframe"]].append(e["backtest_result"]["correct"])
    for tf, results in by_tf.items():
        if results:
            print(f"  {tf}: {sum(results)}/{len(results)} correct "
                  f"({100*sum(results)/len(results):.1f}%)")


if __name__ == "__main__":
    main()
