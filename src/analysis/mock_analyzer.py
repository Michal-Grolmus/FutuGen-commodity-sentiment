"""Keyword-based mock analyzer — replaces Claude API for zero-cost testing.

Detects commodities and sentiment direction from transcript text using pattern matching.
Not as accurate as Claude, but sufficient for pipeline integration testing.
"""
from __future__ import annotations

import logging
import re
import time

from src.models import (
    CommodityMention,
    CommoditySignal,
    Direction,
    ExtractionResult,
    PersonMention,
    ScoringResult,
    Timeframe,
    Transcript,
)

logger = logging.getLogger(__name__)

COMMODITY_KEYWORDS: dict[str, list[str]] = {
    "crude_oil_wti": ["oil", "crude", "wti", "barrel", "opec", "petroleum"],
    "crude_oil_brent": ["brent"],
    "natural_gas": ["natural gas", "lng", "gas supply", "gas import"],
    "gold": ["gold", "precious metal", "bullion"],
    "silver": ["silver"],
    "wheat": ["wheat"],
    "corn": ["corn", "crop", "grain", "harvest"],
    "copper": ["copper", "industrial metal", "mine"],
}

DISPLAY_NAMES: dict[str, str] = {
    "crude_oil_wti": "WTI Crude Oil",
    "crude_oil_brent": "Brent Crude Oil",
    "natural_gas": "Natural Gas",
    "gold": "Gold",
    "silver": "Silver",
    "wheat": "Wheat",
    "corn": "Corn",
    "copper": "Copper",
}

BULLISH = [
    "cut production", "production cut", "reduce supply", "supply disruption",
    "strike", "sanctions", "ban", "drought", "shortage", "escalat", "attack",
    "tension", "inflation", "cpi above", "rate cut", "dovish", "expansion",
    "recovery", "demand growth", "record high",
]

BEARISH = [
    "inventory build", "oversupply", "surplus", "weak demand", "rate hike",
    "rate increase", "hawkish", "strong dollar", "slowdown", "recession",
    "inventory increase", "stockpile",
]


class MockExtractor:
    async def extract(self, transcript: Transcript) -> ExtractionResult:
        t0 = time.perf_counter()
        text = transcript.full_text.lower()

        commodities = []
        for name, keywords in COMMODITY_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    idx = text.index(kw)
                    context = transcript.full_text[max(0, idx - 20):idx + len(kw) + 20]
                    commodities.append(CommodityMention(
                        name=name, display_name=DISPLAY_NAMES[name], context=context,
                    ))
                    break

        people: list[PersonMention] = []
        for match in re.finditer(r"(?:chairman|minister|governor|secretary)\s+\w+", text):
            people.append(PersonMention(
                name=match.group(0).title(), role=None, context=match.group(0),
            ))

        return ExtractionResult(
            chunk_id=transcript.chunk_id,
            commodities=commodities,
            people=people,
            indicators=[],
            raw_text=transcript.full_text,
            model_used="mock-keyword",
            input_tokens=len(text.split()),
            output_tokens=0,
            processing_time_s=time.perf_counter() - t0,
        )


class MockScorer:
    async def score(self, extraction: ExtractionResult) -> ScoringResult:
        t0 = time.perf_counter()
        if not extraction.commodities:
            return ScoringResult(
                chunk_id=extraction.chunk_id, signals=[], model_used="mock-keyword",
                input_tokens=0, output_tokens=0, processing_time_s=0.0,
            )

        text = extraction.raw_text.lower()
        bull = sum(1 for kw in BULLISH if kw in text)
        bear = sum(1 for kw in BEARISH if kw in text)

        if bull > bear:
            direction = Direction.BULLISH
            confidence = min(0.9, 0.5 + bull * 0.1)
        elif bear > bull:
            direction = Direction.BEARISH
            confidence = min(0.9, 0.5 + bear * 0.1)
        else:
            direction = Direction.NEUTRAL
            confidence = 0.4

        signals = [
            CommoditySignal(
                commodity=c.name,
                display_name=c.display_name,
                direction=direction,
                confidence=round(confidence, 2),
                rationale=f"Keyword analysis: {bull} bullish vs {bear} bearish indicators.",
                timeframe=Timeframe.SHORT_TERM,
                source_text=c.context,
            )
            for c in extraction.commodities
        ]

        for sig in signals:
            logger.info(
                "MockSignal %s: %s %s (conf=%.2f)",
                extraction.chunk_id, sig.commodity, sig.direction.value, sig.confidence,
            )

        return ScoringResult(
            chunk_id=extraction.chunk_id,
            signals=signals,
            model_used="mock-keyword",
            input_tokens=len(text.split()),
            output_tokens=0,
            processing_time_s=time.perf_counter() - t0,
        )
