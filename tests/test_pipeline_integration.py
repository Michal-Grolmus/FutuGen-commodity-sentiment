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

# Segment-check verdict (returned when the system prompt is the segment
# aggregator's, detected by the "SEGMENT" marker). Must match the schema
# _llm_verdict parses: summary, direction, confidence, rationale, continue,
# sentiment_arc, timeframe.
MOCK_SEGMENT_VERDICT = json.dumps({
    "continue": False,
    "summary": "OPEC production cut narrative — bullish WTI",
    "direction": "bullish",
    "confidence": 0.82,
    "rationale": "Supply reduction + demand stable = upward pressure",
    "sentiment_arc": None,
    "timeframe": "short_term",
})


def _make_mock_client():
    """Mock Anthropic client that routes by system-prompt content.

    Detects segment-aggregator calls (system prompt contains 'SEGMENT') and
    returns a segment verdict; otherwise alternates extraction / scoring
    responses for per-chunk analysis.
    """
    client = AsyncMock()
    call_count = {"extract_or_score": 0}

    async def mock_create(**kwargs):
        system = kwargs.get("system", "") or ""
        # The SegmentAggregator's system prompt is SEGMENT_SYSTEM_PROMPT.
        # Match on "segment tracker" (its opening line) to route these
        # separately from the extractor/scorer prompts.
        if "segment tracker" in str(system).lower():
            msg = MagicMock()
            msg.usage.input_tokens = 150
            msg.usage.output_tokens = 100
            msg.content = [MagicMock(text=MOCK_SEGMENT_VERDICT)]
            return msg

        call_count["extract_or_score"] += 1
        msg = MagicMock()
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 150
        if call_count["extract_or_score"] % 2 == 1:
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
async def test_segments_close_when_vod_source_drains():
    """Regression: after a short VOD finishes, every segment that was opened
    for its primary commodities must emit a segment.close event with a
    populated summary — NOT stay in "Active / Analyzing…" forever.

    Mocks the LLM so we don't need an API key; feeds a real audio sample
    through the pipeline; asserts that the broadcasted events end with a
    close per opened segment and that each close snapshot has a non-empty
    summary + a non-neutral direction (final close-time LLM verdict ran).
    """
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
        anthropic_api_key="test-key",
        chunk_duration_s=15,
        pipeline_timeout_s=60,
    )

    mock_client = _make_mock_client()

    with patch("src.pipeline.AsyncAnthropic", return_value=mock_client):
        pipeline = Pipeline(settings, broadcaster)
        await pipeline.run()

    open_events = [e for e in events if e.event_type == "segment.open"]
    close_events = [e for e in events if e.event_type == "segment.close"]

    # Sanity: at least one segment was opened for the mocked commodity
    assert len(open_events) > 0, "Expected at least one segment.open"

    # Every opened segment must close (ids should match)
    opened_ids = {e.segment.segment_id for e in open_events if e.segment}
    closed_ids = {e.segment.segment_id for e in close_events if e.segment}
    assert opened_ids == closed_ids, (
        f"Some segments never closed. opened-not-closed="
        f"{opened_ids - closed_ids}"
    )

    # Every close snapshot must carry a real summary + direction — proves
    # the close-time LLM verdict ran and the UI won't show "Analyzing…".
    for ev in close_events:
        seg = ev.segment
        assert seg is not None
        assert seg.is_closed is True
        assert seg.summary, f"Segment {seg.segment_id} closed with empty summary"
        assert seg.direction.value != "neutral" or seg.confidence > 0, (
            f"Segment {seg.segment_id} closed with placeholder state "
            f"(direction=neutral, confidence={seg.confidence})"
        )


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
