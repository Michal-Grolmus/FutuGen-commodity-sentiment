"""Integration test: full pipeline flow with mocked Claude API."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.dashboard.server import SignalBroadcaster
from src.models import PipelineEvent
from src.pipeline import Pipeline

SAMPLE_FILE = "audio_samples/sample_01_opec.wav"

MOCK_EXTRACTION = json.dumps({
    "commodities": [
        {"name": "crude_oil_wti", "display_name": "WTI Crude Oil", "context": "production cut"},
    ],
    "people": [
        {"name": "OPEC Minister", "role": "OPEC", "context": "announced"},
    ],
    "indicators": [
        {"name": "oil_production", "display_name": "Oil Production", "context": "cut"},
    ],
})

MOCK_SCORING = json.dumps({
    "signals": [{
        "commodity": "crude_oil_wti",
        "display_name": "WTI Crude Oil",
        "direction": "bullish",
        "confidence": 0.85,
        "rationale": "Production cut reduces supply, pushing prices higher.",
        "timeframe": "short_term",
        "source_text": "production cut",
        "speaker": None,
    }]
})


def _make_mock_client():
    """Create mock Anthropic client alternating extraction/scoring responses."""
    client = AsyncMock()
    call_count = {"n": 0}

    async def mock_create(**kwargs):
        call_count["n"] += 1
        msg = MagicMock()
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 150
        if call_count["n"] % 2 == 1:
            msg.content = [MagicMock(text=MOCK_EXTRACTION)]
        else:
            msg.content = [MagicMock(text=MOCK_SCORING)]
        return msg

    client.messages.create = mock_create
    return client


@pytest.mark.asyncio
async def test_full_pipeline_end_to_end():
    """Test complete pipeline: file → transcribe → extract → score → broadcast."""
    if not Path(SAMPLE_FILE).exists():
        pytest.skip("TTS sample not generated")

    # Collect all events broadcast by the pipeline
    events: list[PipelineEvent] = []
    broadcaster = SignalBroadcaster()
    original_publish = broadcaster.publish

    async def capturing_publish(event: PipelineEvent) -> None:
        events.append(event)
        await original_publish(event)

    broadcaster.publish = capturing_publish

    settings = Settings(
        input_file=SAMPLE_FILE,
        whisper_model_size="tiny",
        whisper_language="en",
        anthropic_api_key="test-key",
        chunk_duration_s=15,
        pipeline_timeout_s=60,
    )

    mock_client = _make_mock_client()

    with patch("src.pipeline.AsyncAnthropic", return_value=mock_client):
        pipeline = Pipeline(settings, broadcaster)
        await pipeline.run()

    # Verify events were generated
    transcript_events = [e for e in events if e.event_type == "transcript"]
    extraction_events = [e for e in events if e.event_type == "extraction"]
    signal_events = [e for e in events if e.event_type == "signal"]

    assert len(transcript_events) > 0, "Should have at least one transcript event"
    assert len(extraction_events) > 0, "Should have at least one extraction event"
    assert len(signal_events) > 0, "Should have at least one signal event"

    # Verify transcript content
    first_transcript = transcript_events[0].transcript
    assert first_transcript is not None
    assert "opec" in first_transcript.full_text.lower() or "production" in first_transcript.full_text.lower()

    # Verify signals contain expected commodity
    first_signal = signal_events[0].scoring
    assert first_signal is not None
    assert len(first_signal.signals) > 0
    assert first_signal.signals[0].commodity == "crude_oil_wti"
    assert first_signal.signals[0].direction.value == "bullish"

    # Verify stats accumulated
    stats = broadcaster.get_stats()
    assert stats["chunks_processed"] > 0
    assert stats["total_signals"] > 0


@pytest.mark.asyncio
async def test_pipeline_without_api_key():
    """Pipeline should work without API key (transcription only mode)."""
    if not Path(SAMPLE_FILE).exists():
        pytest.skip("TTS sample not generated")

    events: list[PipelineEvent] = []
    broadcaster = SignalBroadcaster()
    original_publish = broadcaster.publish

    async def capturing_publish(event: PipelineEvent) -> None:
        events.append(event)
        await original_publish(event)

    broadcaster.publish = capturing_publish

    settings = Settings(
        input_file=SAMPLE_FILE,
        whisper_model_size="tiny",
        whisper_language="en",
        anthropic_api_key="",  # No API key
        chunk_duration_s=15,
        pipeline_timeout_s=60,
    )

    pipeline = Pipeline(settings, broadcaster)
    await pipeline.run()

    # Should have transcripts but no extraction/signal events with real data
    transcript_events = [e for e in events if e.event_type == "transcript"]
    assert len(transcript_events) > 0, "Should still transcribe without API key"
