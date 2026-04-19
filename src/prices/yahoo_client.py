from __future__ import annotations

import logging

import yfinance as yf

logger = logging.getLogger(__name__)

COMMODITY_TICKERS: dict[str, str] = {
    "crude_oil_wti": "CL=F",
    "crude_oil_brent": "BZ=F",
    "natural_gas": "NG=F",
    "gold": "GC=F",
    "silver": "SI=F",
    "wheat": "ZW=F",
    "corn": "ZC=F",
    "copper": "HG=F",
}


class _YfinanceNoiseFilter(logging.Filter):
    """Drop yfinance's misleading 'possibly delisted' ERROR lines.

    The message fires whenever yfinance gets an empty response for a short
    period (period=1d on a weekend/holiday, stale CDN). Our callers already
    handle empty DataFrames — they don't need a scary ERROR in the log for
    something we've gracefully fallen back from.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "possibly delisted" in msg:
            return False
        # Same pattern, slightly different spelling used by some versions
        if "No price data found" in msg and "delisted" in msg:
            return False
        return True


# Install the filter once at module import. yfinance logs through its own
# top-level logger (and child loggers like yfinance.history); attaching to
# the parent is enough because logging propagates.
_yf_logger = logging.getLogger("yfinance")
if not any(isinstance(f, _YfinanceNoiseFilter) for f in _yf_logger.filters):
    _yf_logger.addFilter(_YfinanceNoiseFilter())


def _fetch_history(ticker: str, period: str) -> object:
    """yf.Ticker(...).history(period=...) with a fallback to a longer
    window when the short one comes back empty.

    Futures markets close on weekends + holidays, so period='1d' can be
    empty late Friday through Monday open. Retrying with '5d' covers the
    gap without surfacing a user-visible error.
    """
    try:
        hist = yf.Ticker(ticker).history(period=period)
    except Exception:
        logger.exception("yfinance history() raised for %s period=%s", ticker, period)
        return None
    if hist is None or hist.empty:
        if period in ("1d", "2d"):
            try:
                hist = yf.Ticker(ticker).history(period="5d")
            except Exception:
                logger.exception("yfinance fallback history() raised for %s", ticker)
                return None
            if hist is None or hist.empty:
                return None
        else:
            return None
    return hist


class PriceClient:
    def get_current_price(self, commodity: str) -> float | None:
        ticker = COMMODITY_TICKERS.get(commodity)
        if not ticker:
            return None
        hist = _fetch_history(ticker, "1d")
        if hist is None:
            return None
        try:
            return float(hist["Close"].iloc[-1])
        except (KeyError, IndexError, ValueError):
            return None

    def get_history(self, commodity: str, period: str = "1mo") -> list[dict[str, object]]:
        """Get historical price data as list of {date, close} dicts for sparkline charts."""
        ticker = COMMODITY_TICKERS.get(commodity)
        if not ticker:
            return []
        hist = _fetch_history(ticker, period)
        if hist is None:
            return []
        try:
            return [
                {"date": str(idx.date()), "close": round(float(row["Close"]), 2)}
                for idx, row in hist.iterrows()
            ]
        except Exception:
            logger.exception("Failed to parse history for %s", commodity)
            return []

    def get_all_prices(self) -> dict[str, dict[str, object]]:
        """Get current prices for all tracked commodities."""
        result = {}
        for commodity, display in [
            ("crude_oil_wti", "WTI Crude"),
            ("crude_oil_brent", "Brent Crude"),
            ("natural_gas", "Natural Gas"),
            ("gold", "Gold"),
            ("silver", "Silver"),
            ("wheat", "Wheat"),
            ("corn", "Corn"),
            ("copper", "Copper"),
        ]:
            price = self.get_current_price(commodity)
            change = self.get_price_change_24h(commodity)
            if price is not None:
                result[commodity] = {
                    "display_name": display,
                    "price": price,
                    "change_24h": change,
                }
        return result

    def get_price_change_24h(self, commodity: str) -> float | None:
        ticker = COMMODITY_TICKERS.get(commodity)
        if not ticker:
            return None
        hist = _fetch_history(ticker, "2d")
        if hist is None:
            return None
        try:
            if len(hist) < 2:
                return None
            return float(hist["Close"].iloc[-1] - hist["Close"].iloc[-2])
        except (KeyError, IndexError, ValueError):
            return None
