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


class PriceClient:
    def get_current_price(self, commodity: str) -> float | None:
        ticker = COMMODITY_TICKERS.get(commodity)
        if not ticker:
            return None
        try:
            data = yf.Ticker(ticker)
            hist = data.history(period="1d")
            if hist.empty:
                return None
            return float(hist["Close"].iloc[-1])
        except Exception:
            logger.exception("Failed to fetch price for %s", commodity)
            return None

    def get_price_change_24h(self, commodity: str) -> float | None:
        ticker = COMMODITY_TICKERS.get(commodity)
        if not ticker:
            return None
        try:
            data = yf.Ticker(ticker)
            hist = data.history(period="2d")
            if len(hist) < 2:
                return None
            return float(hist["Close"].iloc[-1] - hist["Close"].iloc[-2])
        except Exception:
            logger.exception("Failed to fetch price change for %s", commodity)
            return None
