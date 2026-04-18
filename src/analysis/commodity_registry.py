"""Runtime registry of tracked commodities.

Starts with 8 default commodities but can be extended at runtime via the dashboard.
Used by both extractor/scorer (for LLM prompts) and mock analyzer (for keyword detection).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CommodityDef:
    """A tracked commodity: what it's called, how to detect it, how to price it."""

    name: str               # snake_case canonical ID (e.g. "crude_oil_wti")
    display_name: str       # human-readable (e.g. "WTI Crude Oil")
    keywords: list[str] = field(default_factory=list)  # for mock analyzer
    yahoo_ticker: str = ""  # for price data (e.g. "CL=F")


# Default registry — starts here, can be extended at runtime
_REGISTRY: dict[str, CommodityDef] = {
    "crude_oil_wti": CommodityDef(
        "crude_oil_wti", "WTI Crude Oil",
        ["oil", "crude", "wti", "barrel", "opec", "petroleum"], "CL=F",
    ),
    "crude_oil_brent": CommodityDef(
        "crude_oil_brent", "Brent Crude Oil", ["brent"], "BZ=F",
    ),
    "natural_gas": CommodityDef(
        "natural_gas", "Natural Gas",
        ["natural gas", "lng", "gas supply", "gas import"], "NG=F",
    ),
    "gold": CommodityDef(
        "gold", "Gold", ["gold", "precious metal", "bullion"], "GC=F",
    ),
    "silver": CommodityDef("silver", "Silver", ["silver"], "SI=F"),
    "wheat": CommodityDef("wheat", "Wheat", ["wheat"], "ZW=F"),
    "corn": CommodityDef("corn", "Corn", ["corn", "crop", "grain", "harvest"], "ZC=F"),
    "copper": CommodityDef(
        "copper", "Copper", ["copper", "industrial metal", "mine"], "HG=F",
    ),
}


def all_commodities() -> list[CommodityDef]:
    return list(_REGISTRY.values())


def get(name: str) -> CommodityDef | None:
    return _REGISTRY.get(name)


def add(name: str, display_name: str, keywords: list[str], yahoo_ticker: str = "") -> CommodityDef:
    """Add a new commodity at runtime."""
    if name in _REGISTRY:
        raise ValueError(f"Commodity '{name}' already exists")
    c = CommodityDef(name=name, display_name=display_name, keywords=keywords, yahoo_ticker=yahoo_ticker)
    _REGISTRY[name] = c
    return c


def remove(name: str) -> bool:
    """Remove a commodity. Returns True if removed, False if not found."""
    return _REGISTRY.pop(name, None) is not None


def canonical_map() -> dict[str, str]:
    """Legacy format: {name: display_name} for prompt building."""
    return {c.name: c.display_name for c in _REGISTRY.values()}


def keyword_map() -> dict[str, list[str]]:
    """For mock analyzer: {name: [keywords...]}"""
    return {c.name: c.keywords for c in _REGISTRY.values() if c.keywords}


def ticker_map() -> dict[str, str]:
    """For Yahoo Finance: {name: ticker}"""
    return {c.name: c.yahoo_ticker for c in _REGISTRY.values() if c.yahoo_ticker}
