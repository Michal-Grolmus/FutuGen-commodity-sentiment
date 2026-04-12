"""Tests for Yahoo Finance price client."""
from __future__ import annotations

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
