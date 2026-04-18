from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models import (
    CommodityMention,
    EconomicIndicator,
    ExtractionResult,
    PersonMention,
    Transcript,
    TranscriptSegment,
    WordTimestamp,
)


@pytest.fixture
def sample_transcript() -> Transcript:
    return Transcript(
        chunk_id="test_chunk_01",
        language="en",
        language_probability=0.98,
        segments=[
            TranscriptSegment(
                segment_id=0,
                start=0.0,
                end=5.0,
                text="OPEC has announced a production cut of one million barrels per day.",
                words=[
                    WordTimestamp(word="OPEC", start=0.0, end=0.3, probability=0.95),
                    WordTimestamp(word="has", start=0.3, end=0.5, probability=0.99),
                    WordTimestamp(word="announced", start=0.5, end=1.0, probability=0.97),
                ],
                avg_logprob=-0.3,
                no_speech_prob=0.01,
            ),
        ],
        full_text="OPEC has announced a production cut of one million barrels per day.",
        processing_time_s=1.2,
    )


@pytest.fixture
def sample_extraction() -> ExtractionResult:
    return ExtractionResult(
        chunk_id="test_chunk_01",
        commodities=[
            CommodityMention(
                name="crude_oil_wti",
                display_name="WTI Crude Oil",
                context="production cut of one million barrels",
            ),
            CommodityMention(
                name="crude_oil_brent",
                display_name="Brent Crude Oil",
                context="production cut of one million barrels",
            ),
        ],
        people=[
            PersonMention(
                name="Saudi Energy Minister",
                role="OPEC representative",
                context="OPEC has announced",
            ),
        ],
        indicators=[
            EconomicIndicator(
                name="oil_production",
                display_name="Oil Production",
                context="production cut of one million barrels per day",
            ),
        ],
        raw_text="OPEC has announced a production cut of one million barrels per day.",
        model_used="claude-haiku-4-5-20251001",
        input_tokens=150,
        output_tokens=200,
        processing_time_s=0.8,
    )


@pytest.fixture
def mock_extraction_response() -> dict:
    return {
        "commodities": [
            {"name": "crude_oil_wti", "display_name": "WTI Crude Oil", "context": "production cut"},
            {"name": "crude_oil_brent", "display_name": "Brent Crude Oil", "context": "production cut"},
        ],
        "people": [
            {"name": "Saudi Minister", "role": "OPEC", "context": "announced"},
        ],
        "indicators": [
            {"name": "oil_production", "display_name": "Oil Production", "context": "cut of one million barrels"},
        ],
    }


@pytest.fixture
def mock_scoring_response() -> dict:
    return {
        "signals": [
            {
                "commodity": "crude_oil_wti",
                "display_name": "WTI Crude Oil",
                "direction": "bullish",
                "confidence": 0.85,
                "rationale": "OPEC production cuts reduce supply, pushing prices higher.",
                "timeframe": "short_term",
                "source_text": "production cut of one million barrels per day",
                "speaker": None,
            },
        ],
    }


@pytest.fixture
def mock_anthropic_client(mock_extraction_response: dict, mock_scoring_response: dict) -> AsyncMock:
    """Create a mock Anthropic client that returns predetermined responses."""
    client = AsyncMock()

    # Track call count to alternate responses
    call_count = {"n": 0}

    async def mock_create(**kwargs):
        call_count["n"] += 1
        msg = MagicMock()
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 150

        # First call = extraction, second call = scoring
        if call_count["n"] % 2 == 1:
            msg.content = [MagicMock(text=json.dumps(mock_extraction_response))]
        else:
            msg.content = [MagicMock(text=json.dumps(mock_scoring_response))]
        return msg

    client.messages.create = mock_create
    return client


@pytest.fixture
def mock_openai_client(mock_extraction_response: dict, mock_scoring_response: dict) -> AsyncMock:
    """Mock OpenAI AsyncClient shaped like chat.completions.create(...)."""
    client = AsyncMock()
    call_count = {"n": 0}

    async def mock_create(**kwargs):
        call_count["n"] += 1
        resp = MagicMock()
        resp.usage.prompt_tokens = 100
        resp.usage.completion_tokens = 150
        payload = mock_extraction_response if call_count["n"] % 2 == 1 else mock_scoring_response
        choice = MagicMock()
        choice.message.content = json.dumps(payload)
        resp.choices = [choice]
        return resp

    client.chat.completions.create = mock_create
    return client
