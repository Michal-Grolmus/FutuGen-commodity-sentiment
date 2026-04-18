"""Simple P&L simulation of a signal-following strategy.

Rules:
  - For each prediction with direction in {bullish, bearish} AND confidence
    >= `threshold`, enter a position at d0 close.
  - Hold for `horizon` trading days, exit at d{horizon} close.
  - Position size = 1 (unit) per signal; long for bullish, short for bearish.
  - Returns are log returns (simple pct change is fine for small moves but
    log is standard for strategy reporting).

Outputs:
  - total return
  - annualized Sharpe ratio
  - max drawdown
  - win rate
  - average win / average loss
  - trade count

Limitations explicitly reported:
  - No transaction costs (would knock 0.05-0.15% off each trade in futures)
  - No slippage
  - No position sizing (each trade equally weighted)
  - No portfolio constraint (overlapping trades are treated independently)
"""
from __future__ import annotations

import math


def trade_return(
    direction: str,
    price_entry: float,
    price_exit: float,
) -> float:
    """Log return of the trade. Positive = profit."""
    if price_entry <= 0 or price_exit <= 0:
        return 0.0
    raw_log = math.log(price_exit / price_entry)
    if direction == "bullish":
        return raw_log
    if direction == "bearish":
        return -raw_log
    return 0.0


def simulate(
    predictions: list[dict],
    events: list[dict],
    *,
    horizon: int = 7,
    threshold: float = 0.6,
    conf_key: str = "confidence",
) -> dict[str, object]:
    """Run the strategy and return summary metrics.

    `predictions` must be aligned with `events` (same order). Each prediction
    has `direction`, `confidence` (or `conf_key`). Events have `prices.d0`,
    `prices.d{horizon}`.
    """
    if len(predictions) != len(events):
        raise ValueError("predictions and events must be aligned")

    price_key_entry = "d0"
    price_key_exit = f"d{horizon}"

    trades: list[dict[str, object]] = []
    for pred, ev in zip(predictions, events, strict=False):
        direction = pred.get("direction", "neutral")
        if direction not in ("bullish", "bearish"):
            continue
        conf = float(pred.get(conf_key, 0.0))
        if conf < threshold:
            continue
        prices = ev.get("prices", {})
        entry = prices.get(price_key_entry)
        exit_price = prices.get(price_key_exit)
        if entry is None or exit_price is None:
            continue
        r = trade_return(direction, float(entry), float(exit_price))
        trades.append({
            "event_id": ev["event_id"],
            "commodity": ev["commodity"],
            "direction": direction,
            "confidence": conf,
            "entry": float(entry),
            "exit": float(exit_price),
            "return": r,
        })

    if not trades:
        return {
            "horizon_days": horizon,
            "confidence_threshold": threshold,
            "trades": 0,
            "total_return": 0.0,
            "mean_return": 0.0,
            "sharpe": None,
            "max_drawdown": 0.0,
            "win_rate": None,
            "avg_win": None,
            "avg_loss": None,
            "note": "No trades above threshold.",
        }

    returns = [float(t["return"]) for t in trades]
    total_return = sum(returns)
    mean_r = total_return / len(returns)
    stdev = (sum((r - mean_r) ** 2 for r in returns) / len(returns)) ** 0.5 if len(returns) > 1 else 0.0
    # Annualize: ~252 trading days / horizon -> trades per year per event slot
    # Sharpe uses mean / stdev * sqrt(periods_per_year)
    periods_per_year = 252 / max(horizon, 1)
    sharpe = (mean_r / stdev * math.sqrt(periods_per_year)) if stdev > 0 else None

    # Equity curve + max drawdown
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in returns:
        equity += r
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    win_rate = len(wins) / len(returns) if returns else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    return {
        "horizon_days": horizon,
        "confidence_threshold": threshold,
        "trades": len(trades),
        "total_return": total_return,
        "mean_return": mean_r,
        "return_stdev": stdev,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "trade_list": trades,
    }
