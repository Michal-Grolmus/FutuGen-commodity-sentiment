from __future__ import annotations

import pytest

from src.analysis.impact_scorer import ImpactScorer
from src.models import Direction, ExtractionResult, Timeframe


@pytest.mark.asyncio
async def test_score_bullish_signal(mock_anthropic_client, sample_extraction):
    # Reset call counter — extraction fixture already used 1 call in conftest
    scorer = ImpactScorer(mock_anthropic_client, model="claude-haiku-4-5-20251001")

    # The mock returns scoring response on even calls
    # Force the mock to return scoring response
    import json
    from unittest.mock import MagicMock

    scoring_resp = {
        "signals": [{
            "commodity": "crude_oil_wti",
            "display_name": "WTI Crude Oil",
            "direction": "bullish",
            "confidence": 0.85,
            "rationale": "Production cuts reduce supply.",
            "timeframe": "short_term",
            "source_text": "production cut",
            "speaker": None,
        }]
    }

    async def mock_create(**kwargs):
        msg = MagicMock()
        msg.usage.input_tokens = 200
        msg.usage.output_tokens = 150
        msg.content = [MagicMock(text=json.dumps(scoring_resp))]
        return msg

    mock_anthropic_client.messages.create = mock_create

    result = await scorer.score(sample_extraction)

    assert result.chunk_id == sample_extraction.chunk_id
    assert len(result.signals) == 1
    assert result.signals[0].direction == Direction.BULLISH
    assert result.signals[0].confidence == 0.85
    assert result.signals[0].timeframe == Timeframe.SHORT_TERM


@pytest.mark.asyncio
async def test_score_no_commodities(mock_anthropic_client):
    empty_extraction = ExtractionResult(
        chunk_id="empty",
        commodities=[],
        people=[],
        indicators=[],
        raw_text="general market commentary",
        model_used="test",
        input_tokens=0,
        output_tokens=0,
        processing_time_s=0.0,
    )
    scorer = ImpactScorer(mock_anthropic_client)
    result = await scorer.score(empty_extraction)

    assert result.chunk_id == "empty"
    assert len(result.signals) == 0
    assert result.input_tokens == 0
