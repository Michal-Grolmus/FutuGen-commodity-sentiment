from __future__ import annotations

import json

import pytest

from src.analysis.llm import complete


@pytest.mark.asyncio
async def test_complete_anthropic(mock_anthropic_client, mock_extraction_response):
    resp = await complete(
        mock_anthropic_client,
        "anthropic",
        model="claude-haiku-4-5-20251001",
        system="sys",
        user="hello",
    )
    assert json.loads(resp.text) == mock_extraction_response
    assert resp.input_tokens == 100
    assert resp.output_tokens == 150


@pytest.mark.asyncio
async def test_complete_openai(mock_openai_client, mock_extraction_response):
    resp = await complete(
        mock_openai_client,
        "openai",
        model="gpt-4o-mini",
        system="sys",
        user="hello",
    )
    assert json.loads(resp.text) == mock_extraction_response
    assert resp.input_tokens == 100
    assert resp.output_tokens == 150


@pytest.mark.asyncio
async def test_complete_unknown_provider(mock_anthropic_client):
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        await complete(
            mock_anthropic_client,
            "cohere",
            model="irrelevant",
            system="sys",
            user="hello",
        )


@pytest.mark.asyncio
async def test_extractor_with_openai(mock_openai_client, sample_transcript):
    """EntityExtractor should work the same way via OpenAI provider."""
    from src.analysis.entity_extractor import EntityExtractor

    extractor = EntityExtractor(mock_openai_client, model="gpt-4o-mini", provider="openai")
    result = await extractor.extract(sample_transcript)

    assert result.chunk_id == sample_transcript.chunk_id
    assert len(result.commodities) == 2
    assert result.commodities[0].name == "crude_oil_wti"
    assert result.model_used == "gpt-4o-mini"
    assert result.input_tokens > 0


@pytest.mark.asyncio
async def test_scorer_with_openai(mock_openai_client, sample_extraction):
    """ImpactScorer should work via OpenAI provider (returns extraction mock on 1st call,
    but scoring shape still works because the mock returns valid JSON either way)."""
    from src.analysis.impact_scorer import ImpactScorer

    scorer = ImpactScorer(mock_openai_client, model="gpt-4o-mini", provider="openai")
    result = await scorer.score(sample_extraction)

    assert result.chunk_id == sample_extraction.chunk_id
    assert result.model_used == "gpt-4o-mini"
    # First call to mock returns extraction payload (no "signals") — scorer handles it gracefully
    assert isinstance(result.signals, list)
