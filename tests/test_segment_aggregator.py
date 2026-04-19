"""Unit tests for SegmentAggregator.

We mock the LLM client and feed synthetic chunks/signals, then verify:
- First chunk with signals opens a new segment ("open" event)
- Every `check_interval_chunks` chunks, an LLM "continue/close" call runs
- continue=false closes the current segment and starts a new one
- Hard cap (max_chunks_per_segment) force-closes
- Break phrases in transcript auto-close (after at least 2 chunks)
- close_stream() closes all open segments for a stream
- close_all() closes everything (e.g. pipeline shutdown)
- Empty-signal chunks feed existing segments but don't start new ones
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.analysis.segment_aggregator import (
    SegmentAggregator,
    SegmentAggregatorConfig,
)
from src.models import CommoditySignal, Direction, Timeframe, Transcript


def _transcript(chunk_id: str, text: str = "gold prices are rising on central bank demand") -> Transcript:
    return Transcript(
        chunk_id=chunk_id,
        language="en",
        language_probability=0.99,
        segments=[],
        full_text=text,
        processing_time_s=0.5,
    )


def _signal(commodity: str = "gold", direction: str = "bullish",
            confidence: float = 0.75) -> CommoditySignal:
    return CommoditySignal(
        commodity=commodity,
        display_name=commodity.title(),
        direction=Direction(direction),
        confidence=confidence,
        rationale="test rationale",
        timeframe=Timeframe.SHORT_TERM,
        source_text="test source",
    )


def _make_llm_client(verdicts: list[dict]):
    """Mock client whose `messages.create` returns the verdicts sequentially."""
    client = AsyncMock()
    call_count = {"n": 0}

    async def fake_create(**kwargs):
        idx = call_count["n"] % len(verdicts)
        call_count["n"] += 1
        msg = MagicMock()
        msg.usage.input_tokens = 50
        msg.usage.output_tokens = 80
        msg.content = [MagicMock(text=json.dumps(verdicts[idx]))]
        return msg

    client.messages.create = fake_create
    return client


@pytest.fixture
def small_config():
    return SegmentAggregatorConfig(check_interval_chunks=3, max_chunks_per_segment=10)


@pytest.mark.asyncio
async def test_first_chunk_with_signal_opens_segment(small_config):
    agg = SegmentAggregator(_make_llm_client([]), "anthropic", small_config)
    events = await agg.process_chunk("stream_a", _transcript("c1"), [_signal()])
    assert any(kind == "open" for kind, _ in events)
    kind, seg = events[0]
    assert kind == "open"
    assert seg.primary_commodity == "gold"
    assert seg.stream_id == "stream_a"
    assert seg.chunk_ids == ["c1"]


@pytest.mark.asyncio
async def test_chunks_without_signal_dont_open_segment(small_config):
    agg = SegmentAggregator(_make_llm_client([]), "anthropic", small_config)
    events = await agg.process_chunk("stream_a", _transcript("c1", "the weather is nice"), [])
    assert events == []


@pytest.mark.asyncio
async def test_llm_continue_keeps_segment_open(small_config):
    verdicts = [{"continue": True, "summary": "gold bullish segment", "direction": "bullish",
                 "confidence": 0.8, "rationale": "strong demand"}]
    agg = SegmentAggregator(_make_llm_client(verdicts), "anthropic", small_config)
    # Fire enough chunks to trigger a check
    all_events = []
    for i in range(small_config.check_interval_chunks):
        all_events.extend(await agg.process_chunk(
            "stream_a", _transcript(f"c{i}"), [_signal()]))

    # Expect one 'open' (first chunk), then 'update' (on Nth chunk)
    kinds = [k for k, _ in all_events]
    assert "open" in kinds
    assert "update" in kinds
    # Segment should still be active
    assert ("stream_a", "gold") in agg._active


@pytest.mark.asyncio
async def test_llm_close_then_new_segment(small_config):
    verdicts = [
        {"continue": False, "summary": "closing old", "direction": "bullish",
         "confidence": 0.7, "rationale": "topic shift"},
    ]
    agg = SegmentAggregator(_make_llm_client(verdicts), "anthropic", small_config)
    all_events = []
    for i in range(small_config.check_interval_chunks):
        all_events.extend(await agg.process_chunk(
            "stream_a", _transcript(f"c{i}"), [_signal()]))

    kinds = [k for k, _ in all_events]
    assert "open" in kinds
    assert "close" in kinds
    # After close, no active segment
    assert ("stream_a", "gold") not in agg._active

    # Next chunk with a signal should open a NEW segment
    new_events = await agg.process_chunk("stream_a", _transcript("c_new"), [_signal()])
    new_kinds = [k for k, _ in new_events]
    assert "open" in new_kinds


@pytest.mark.asyncio
async def test_hard_cap_force_closes():
    # No check interval reached, but segment grows past max_chunks_per_segment → hard_cap
    cfg = SegmentAggregatorConfig(check_interval_chunks=100, max_chunks_per_segment=5)
    agg = SegmentAggregator(_make_llm_client([]), "anthropic", cfg)
    all_events = []
    for i in range(cfg.max_chunks_per_segment + 1):
        all_events.extend(await agg.process_chunk(
            "stream_a", _transcript(f"c{i}"), [_signal()]))

    close_events = [(k, s) for k, s in all_events if k == "close"]
    assert len(close_events) == 1
    assert close_events[0][1].close_reason == "hard_cap"


@pytest.mark.asyncio
async def test_break_phrase_closes_segment(small_config):
    """A transcript with an explicit break phrase should close the active segment."""
    agg = SegmentAggregator(_make_llm_client([]), "anthropic", small_config)
    # Build up a segment with 2 chunks
    await agg.process_chunk("stream_a", _transcript("c1"), [_signal()])
    await agg.process_chunk("stream_a", _transcript("c2"), [_signal()])
    assert ("stream_a", "gold") in agg._active

    # Third chunk contains a break phrase
    events = await agg.process_chunk(
        "stream_a",
        _transcript("c3", "now let's turn to other markets"),
        [_signal()],
    )
    kinds = [k for k, _ in events]
    assert "close" in kinds
    # Last close event should have close_reason break_phrase
    closes = [s for k, s in events if k == "close"]
    assert any(s.close_reason == "break_phrase" for s in closes)


@pytest.mark.asyncio
async def test_close_stream_ends_all_segments_for_that_stream(small_config):
    agg = SegmentAggregator(_make_llm_client([]), "anthropic", small_config)
    await agg.process_chunk("stream_a", _transcript("c1"), [_signal("gold")])
    await agg.process_chunk("stream_b", _transcript("c2"), [_signal("silver")])
    assert len(agg._active) == 2

    closed = await agg.close_stream("stream_a", reason="stream_removed")
    assert len(closed) == 1
    kind, seg = closed[0]
    assert kind == "close"
    assert seg.stream_id == "stream_a"
    assert seg.close_reason == "stream_removed"
    # stream_b still active
    assert ("stream_b", "silver") in agg._active


@pytest.mark.asyncio
async def test_close_all_ends_everything(small_config):
    agg = SegmentAggregator(_make_llm_client([]), "anthropic", small_config)
    await agg.process_chunk("stream_a", _transcript("c1"), [_signal("gold")])
    await agg.process_chunk("stream_b", _transcript("c2"), [_signal("silver")])

    closed = await agg.close_all(reason="pipeline_stopped")
    assert len(closed) == 2
    assert len(agg._active) == 0


@pytest.mark.asyncio
async def test_close_runs_final_llm_verdict_on_unanalyzed_segment(small_config):
    """Short VOD ends before check_interval_chunks — close-time verdict should
    still populate summary + direction instead of leaving them blank."""
    verdicts = [{
        "continue": False,  # irrelevant here; close is forced
        "summary": "Gold rallied on central bank demand",
        "direction": "bullish",
        "confidence": 0.8,
        "rationale": "consistent buy signals in every chunk",
        "timeframe": "short_term",
    }]
    agg = SegmentAggregator(_make_llm_client(verdicts), "anthropic", small_config)

    # 2 chunks with signals (below the 3-chunk check interval) so the LLM
    # has never run during normal process_chunk flow.
    await agg.process_chunk("stream_a", _transcript("c1"), [_signal("gold")])
    await agg.process_chunk("stream_a", _transcript("c2"), [_signal("gold")])
    # Sanity: segment is open with default state (no summary yet)
    key = ("stream_a", "gold")
    active = agg._active[key]
    assert active.summary == ""
    assert active.direction == Direction.NEUTRAL

    closed = await agg.close_stream("stream_a", reason="stream_ended")
    assert len(closed) == 1
    kind, seg = closed[0]
    assert kind == "close"
    # Final verdict populated the snapshot so the UI shows real content
    # instead of "neutral 0% / Analyzing…".
    assert seg.summary == "Gold rallied on central bank demand"
    assert seg.direction == Direction.BULLISH
    assert seg.confidence > 0
    assert seg.close_reason == "stream_ended"


@pytest.mark.asyncio
async def test_close_preserves_existing_verdict_when_already_analyzed(small_config):
    """If the LLM already ran mid-segment, close shouldn't re-run it."""
    mid_verdict = {
        "continue": True, "summary": "mid-segment summary",
        "direction": "bullish", "confidence": 0.7,
        "rationale": "mid rationale", "timeframe": "short_term",
    }
    # Only one verdict configured — a second LLM call would wrap around and
    # be a bug, so count must stay at 1.
    agg = SegmentAggregator(_make_llm_client([mid_verdict]), "anthropic", small_config)

    # 3 chunks == check_interval_chunks → mid-segment verdict fires
    for i in range(3):
        await agg.process_chunk("stream_a", _transcript(f"c{i}"), [_signal("gold")])

    active = agg._active[("stream_a", "gold")]
    assert active.summary == "mid-segment summary"

    closed = await agg.close_stream("stream_a", reason="stream_ended")
    _, seg = closed[0]
    # Existing summary kept — no second verdict
    assert seg.summary == "mid-segment summary"


@pytest.mark.asyncio
async def test_secondary_commodity_tracked(small_config):
    """When a segment sees both gold and silver signals, silver should be
    listed as secondary (or start its own parallel segment)."""
    agg = SegmentAggregator(_make_llm_client([]), "anthropic", small_config)
    await agg.process_chunk(
        "stream_a", _transcript("c1"),
        [_signal("gold"), _signal("silver")],
    )
    # Two active segments (one per commodity — parallel)
    assert ("stream_a", "gold") in agg._active
    assert ("stream_a", "silver") in agg._active


@pytest.mark.asyncio
async def test_malformed_llm_response_keeps_segment_open(small_config):
    """LLM returns garbage JSON → segment doesn't crash, stays open, update emitted."""
    client = AsyncMock()

    async def bad_create(**kwargs):
        msg = MagicMock()
        msg.usage.input_tokens = 10
        msg.usage.output_tokens = 10
        msg.content = [MagicMock(text="this is not json at all")]
        return msg

    client.messages.create = bad_create
    agg = SegmentAggregator(client, "anthropic", small_config)

    all_events = []
    for i in range(small_config.check_interval_chunks):
        all_events.extend(await agg.process_chunk(
            "stream_a", _transcript(f"c{i}"), [_signal()]))

    # No close, only open + update (fallback when LLM errors)
    kinds = [k for k, _ in all_events]
    assert "open" in kinds
    assert "update" in kinds
    assert "close" not in kinds
    assert ("stream_a", "gold") in agg._active
