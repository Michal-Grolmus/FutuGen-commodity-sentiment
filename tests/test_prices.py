"""Tests for Yahoo Finance price client."""
from __future__ import annotations

import logging

from src.prices.yahoo_client import COMMODITY_TICKERS, PriceClient


def test_commodity_tickers_complete():
    """All 8 tracked commodities should have ticker mappings."""
    expected = [
        "crude_oil_wti", "crude_oil_brent", "natural_gas",
        "gold", "silver", "wheat", "corn", "copper",
    ]
    for commodity in expected:
        assert commodity in COMMODITY_TICKERS, f"Missing ticker for {commodity}"


def test_unknown_commodity_returns_none():
    client = PriceClient()
    assert client.get_current_price("unknown_commodity") is None
    assert client.get_price_change_24h("unknown_commodity") is None


def test_yfinance_delisted_noise_is_filtered(caplog):
    """yfinance's 'possibly delisted' ERROR is misleading for futures that
    simply have no data for period=1d on weekends/holidays. We suppress
    that exact message while keeping other yfinance ERRORs visible."""
    yf_logger = logging.getLogger("yfinance")
    caplog.set_level(logging.ERROR, logger="yfinance")

    # Suppressed
    yf_logger.error("$CL=F: possibly delisted; no price data found  (period=1d)")
    # Also suppressed (alternate wording)
    yf_logger.error("$BZ=F: No price data found; symbol may be delisted (period=2d)")
    # KEPT — unrelated error
    yf_logger.error("HTTP 502 Bad Gateway from Yahoo endpoint")

    messages = [r.getMessage() for r in caplog.records]
    assert not any("possibly delisted" in m for m in messages), (
        f"Expected 'possibly delisted' to be filtered, got: {messages}"
    )
    assert any("502 Bad Gateway" in m for m in messages), (
        f"Genuine errors must still reach the log. Got: {messages}"
    )
