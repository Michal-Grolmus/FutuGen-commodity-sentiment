from __future__ import annotations

import pytest

from src.analysis.entity_extractor import EntityExtractor
from src.models import Transcript


@pytest.mark.asyncio
async def test_extract_commodities(mock_anthropic_client, sample_transcript):
    extractor = EntityExtractor(mock_anthropic_client, model="claude-haiku-4-5-20251001")
    result = await extractor.extract(sample_transcript)

    assert result.chunk_id == sample_transcript.chunk_id
    assert len(result.commodities) == 2
    assert result.commodities[0].name == "crude_oil_wti"
    assert result.model_used == "claude-haiku-4-5-20251001"
    assert result.input_tokens > 0


@pytest.mark.asyncio
async def test_extract_empty_text(mock_anthropic_client):
    transcript = Transcript(
        chunk_id="empty",
        language="en",
        language_probability=0.99,
        segments=[],
        full_text="",
        processing_time_s=0.1,
    )
    extractor = EntityExtractor(mock_anthropic_client)
    result = await extractor.extract(transcript)

    assert result.chunk_id == "empty"
    assert len(result.commodities) == 0
    assert result.input_tokens == 0
