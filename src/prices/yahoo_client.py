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

    def get_history(self, commodity: str, period: str = "1mo") -> list[dict[str, object]]:
        """Get historical price data as list of {date, close} dicts for sparkline charts."""
        ticker = COMMODITY_TICKERS.get(commodity)
        if not ticker:
            return []
        try:
            data = yf.Ticker(ticker)
            hist = data.history(period=period)
            if hist.empty:
                return []
            return [
                {"date": str(idx.date()), "close": round(float(row["Close"]), 2)}
                for idx, row in hist.iterrows()
            ]
        except Exception:
            logger.exception("Failed to fetch history for %s", commodity)
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
        try:
            data = yf.Ticker(ticker)
            hist = data.history(period="2d")
            if len(hist) < 2:
                return None
            return float(hist["Close"].iloc[-1] - hist["Close"].iloc[-2])
        except Exception:
            logger.exception("Failed to fetch price change for %s", commodity)
            return None
