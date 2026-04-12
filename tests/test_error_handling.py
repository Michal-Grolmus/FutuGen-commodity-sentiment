"""Tests for error handling: malformed JSON, API errors, invalid data."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.analysis.entity_extractor import EntityExtractor
from src.analysis.impact_scorer import ImpactScorer
from src.models import CommodityMention, ExtractionResult, Transcript


def _make_transcript(text: str = "OPEC cut production") -> Transcript:
    return Transcript(
        chunk_id="err_test",
        language="en",
        language_probability=0.99,
        segments=[],
        full_text=text,
        processing_time_s=0.1,
    )


def _make_extraction() -> ExtractionResult:
    return ExtractionResult(
        chunk_id="err_test",
        commodities=[CommodityMention(name="crude_oil_wti", display_name="WTI", context="cut")],
        people=[],
        indicators=[],
        raw_text="OPEC cut production",
        model_used="test",
        input_tokens=100,
        output_tokens=50,
        processing_time_s=0.5,
    )


def _mock_client_with_response(text: str) -> AsyncMock:
    client = AsyncMock()

    async def mock_create(**kwargs):
        msg = MagicMock()
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 50
        msg.content = [MagicMock(text=text)]
        return msg

    client.messages.create = mock_create
    return client


@pytest.mark.asyncio
async def test_extractor_handles_malformed_json():
    """Extractor should return empty result on malformed JSON, not crash."""
    client = _mock_client_with_response("This is not JSON at all {broken")
    extractor = EntityExtractor(client)
    result = await extractor.extract(_make_transcript())
    assert result.chunk_id == "err_test"
    assert len(result.commodities) == 0


@pytest.mark.asyncio
async def test_extractor_handles_partial_json():
    """Extractor should skip invalid items but keep valid ones."""
    partial_json = json.dumps({
        "commodities": [
            {"name": "gold", "display_name": "Gold", "context": "price up"},
            {"invalid": "missing fields"},  # should be skipped
        ],
        "people": [],
        "indicators": [],
    })
    client = _mock_client_with_response(partial_json)
    extractor = EntityExtractor(client)
    result = await extractor.extract(_make_transcript())
    assert len(result.commodities) == 1
    assert result.commodities[0].name == "gold"


@pytest.mark.asyncio
async def test_scorer_handles_malformed_json():
    """Scorer should return empty result on malformed JSON, not crash."""
    client = _mock_client_with_response("not json")
    scorer = ImpactScorer(client)
    result = await scorer.score(_make_extraction())
    assert result.chunk_id == "err_test"
    assert len(result.signals) == 0


@pytest.mark.asyncio
async def test_scorer_handles_invalid_direction():
    """Scorer should skip signals with invalid direction values."""
    bad_signal = json.dumps({
        "signals": [
            {
                "commodity": "gold",
                "display_name": "Gold",
                "direction": "INVALID_VALUE",
                "confidence": 0.5,
                "rationale": "test",
                "timeframe": "short_term",
                "source_text": "test",
            },
        ]
    })
    client = _mock_client_with_response(bad_signal)
    scorer = ImpactScorer(client)
    result = await scorer.score(_make_extraction())
    assert len(result.signals) == 0  # invalid signal skipped


@pytest.mark.asyncio
async def test_scorer_clamps_confidence():
    """Scorer should clamp confidence to [0, 1] range."""
    high_conf = json.dumps({
        "signals": [{
            "commodity": "gold",
            "display_name": "Gold",
            "direction": "bullish",
            "confidence": 5.0,  # way too high
            "rationale": "test",
            "timeframe": "short_term",
            "source_text": "test",
        }]
    })
    client = _mock_client_with_response(high_conf)
    scorer = ImpactScorer(client)
    result = await scorer.score(_make_extraction())
    assert len(result.signals) == 1
    assert result.signals[0].confidence == 1.0
