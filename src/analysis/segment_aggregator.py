"""Segment aggregator — builds hierarchical 'super-events' from chunk-level signals.

Flow per stream:
  1. Incoming chunk (transcript + signals) is buffered per active segment.
  2. Every `check_interval_chunks` (default 6 = 60s at 10s chunks), the LLM is
     asked to continue/close the segment and produce an updated summary +
     overall direction + confidence weighted by recency.
  3. On close (LLM says `continue=false`, hard cap hit, or explicit break
     phrase detected), the segment is persisted to JSONL and a close event
     emitted. A new segment starts with the chunks immediately after.
  4. Primary commodity = the commodity with the most signals so far in the
     segment. Secondary commodities = others that were mentioned.
  5. If a secondary commodity builds enough share (>=30% of signals) to rival
     the primary, a parallel segment is spawned for it.

Stateful (per aggregator instance = per pipeline). `reset()` closes all open.
"""
from __future__ import annotations

import json
import logging
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.analysis.llm import complete
from src.analysis.prompts import SEGMENT_SYSTEM_PROMPT
from src.models import Direction, Segment, Timeframe, Transcript

logger = logging.getLogger(__name__)


# Phrases that forcibly close a segment (case-insensitive substring match)
BREAK_PHRASES = (
    "now let's turn to",
    "turning now to",
    "in other news",
    "in commodity news",
    "speaking of",
    "moving on to",
    "we'll be right back",
    "we'll return after",
    "coming up next",
)


@dataclass
class _ChunkEntry:
    chunk_id: str
    timestamp: datetime
    transcript_text: str
    signals_raw: list[dict[str, Any]]  # serialized CommoditySignal dicts


@dataclass
class _ActiveSegment:
    """In-memory state for an open segment (not yet closed / persisted)."""
    segment_id: str
    stream_id: str
    primary_commodity: str
    start_time: datetime
    chunks_since_last_check: list[_ChunkEntry] = field(default_factory=list)
    all_chunks: list[_ChunkEntry] = field(default_factory=list)
    commodity_mention_count: Counter = field(default_factory=Counter)

    # Running LLM verdict (updated on every check)
    summary: str = ""
    direction: Direction = Direction.NEUTRAL
    confidence: float = 0.0
    rationale: str = ""
    sentiment_arc: str | None = None
    timeframe: Timeframe = Timeframe.SHORT_TERM


@dataclass
class SegmentAggregatorConfig:
    check_interval_chunks: int = 6       # Call LLM every N chunks
    max_chunks_per_segment: int = 90     # Hard cap ~15 min at 10s chunks
    promotion_ratio: float = 0.30        # Secondary promoted to own segment at this share
    recency_halflife_min: float = 2.0    # Weight decay for confidence recomputation
    model: str = "claude-haiku-4-5-20251001"


class SegmentAggregator:
    """Emits segment open/update/close events; caller broadcasts them."""

    def __init__(
        self,
        llm_client: Any,
        provider: str = "anthropic",
        config: SegmentAggregatorConfig | None = None,
    ) -> None:
        self._client = llm_client
        self._provider = provider
        self._config = config or SegmentAggregatorConfig()
        # Active segments keyed by (stream_id, primary_commodity)
        self._active: dict[tuple[str, str], _ActiveSegment] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def process_chunk(
        self,
        stream_id: str,
        transcript: Transcript,
        signals: list[Any],  # list[CommoditySignal]
    ) -> list[tuple[str, Segment]]:
        """Process one chunk. Returns a list of (event_kind, segment) tuples
        to be broadcast. event_kind ∈ {'open', 'update', 'close'}."""
        events: list[tuple[str, Segment]] = []
        chunk_entry = _ChunkEntry(
            chunk_id=transcript.chunk_id,
            timestamp=datetime.now(UTC),
            transcript_text=transcript.full_text,
            signals_raw=[s.model_dump(mode="json") for s in signals],
        )

        # If no signals at all → only feed into existing active segments for this stream.
        # Do not start a new segment on an empty chunk.
        if not signals:
            for key, active in list(self._active.items()):
                if key[0] == stream_id:
                    active.all_chunks.append(chunk_entry)
                    active.chunks_since_last_check.append(chunk_entry)
                    events.extend(await self._maybe_check(active))
            # Break phrase hard-close (transcript-only driven)
            events.extend(await self._apply_break_phrases(stream_id, chunk_entry))
            return events

        # Count commodity mentions in signals; attribute to the most-mentioned one
        by_commodity: dict[str, list[Any]] = {}
        for sig in signals:
            by_commodity.setdefault(sig.commodity, []).append(sig)

        # For each commodity that appeared in this chunk, feed into its active segment
        # (starting a new one if none exists)
        for commodity, commodity_signals in by_commodity.items():
            key = (stream_id, commodity)
            active = self._active.get(key)
            is_new = active is None
            if is_new:
                active = self._new_segment(stream_id, commodity)
                self._active[key] = active

            active.all_chunks.append(chunk_entry)
            active.chunks_since_last_check.append(chunk_entry)
            active.commodity_mention_count[commodity] += len(commodity_signals)

            if is_new:
                # Emit 'open' AFTER the first chunk is attached so the snapshot
                # already reports chunk_ids = [first_id].
                events.append(("open", self._snapshot(active)))

            events.extend(await self._maybe_check(active))

        # Break phrase hard-close
        events.extend(await self._apply_break_phrases(stream_id, chunk_entry))
        return events

    async def close_stream(self, stream_id: str, reason: str = "stream_removed") -> list[tuple[str, Segment]]:
        """Close all open segments for a given stream (e.g. on pipeline stop)."""
        events: list[tuple[str, Segment]] = []
        for key, active in list(self._active.items()):
            if key[0] == stream_id:
                events.append(await self._close_segment(active, reason))
                del self._active[key]
        return events

    async def close_all(self, reason: str = "aggregator_reset") -> list[tuple[str, Segment]]:
        """Close every active segment — used on pipeline shutdown."""
        events: list[tuple[str, Segment]] = []
        for key, active in list(self._active.items()):
            events.append(await self._close_segment(active, reason))
            del self._active[key]
        return events

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _new_segment(self, stream_id: str, commodity: str) -> _ActiveSegment:
        seg_id = f"seg_{uuid.uuid4().hex[:12]}"
        return _ActiveSegment(
            segment_id=seg_id,
            stream_id=stream_id,
            primary_commodity=commodity,
            start_time=datetime.now(UTC),
        )

    async def _maybe_check(self, active: _ActiveSegment) -> list[tuple[str, Segment]]:
        """If enough new chunks have accrued, run LLM topic-change check."""
        if len(active.chunks_since_last_check) < self._config.check_interval_chunks:
            # Hard cap check — force close if segment is too long
            if len(active.all_chunks) >= self._config.max_chunks_per_segment:
                event = await self._close_segment(active, "hard_cap")
                key = (active.stream_id, active.primary_commodity)
                self._active.pop(key, None)
                return [event]
            return []
        return await self._run_topic_check(active)

    async def _run_topic_check(self, active: _ActiveSegment) -> list[tuple[str, Segment]]:
        """Ask the LLM: continue or close. Update segment state accordingly."""
        try:
            verdict = await self._llm_verdict(active)
        except Exception:
            logger.exception("Segment LLM check failed (segment=%s); keeping open",
                             active.segment_id)
            active.chunks_since_last_check.clear()
            return [("update", self._snapshot(active))]

        # Apply verdict to state
        active.summary = verdict.get("summary", active.summary) or active.summary
        active.direction = self._coerce_direction(verdict.get("direction"), active.direction)
        active.confidence = self._weighted_confidence(active, verdict.get("confidence", active.confidence))
        active.rationale = verdict.get("rationale", active.rationale) or active.rationale
        active.sentiment_arc = verdict.get("sentiment_arc") or None
        tf = verdict.get("timeframe")
        if tf in ("short_term", "medium_term"):
            active.timeframe = Timeframe(tf)

        active.chunks_since_last_check.clear()

        if verdict.get("continue", True):
            return [("update", self._snapshot(active))]

        # LLM says close — finalize this segment
        event = await self._close_segment(active, "topic_shift")
        key = (active.stream_id, active.primary_commodity)
        self._active.pop(key, None)
        return [event]

    async def _close_segment(
        self, active: _ActiveSegment, reason: str,
    ) -> tuple[str, Segment]:
        """Persist + return close event for a segment.

        If the segment hasn't had an LLM analysis yet (short VOD that ends
        before check_interval_chunks is reached), run one final verdict now
        so the close snapshot carries a proper summary + direction instead
        of "neutral 0% / Analyzing…" — otherwise users see stuck placeholder
        cards for every commodity mentioned once in a short clip.
        """
        if active.all_chunks and not active.summary:
            try:
                verdict = await self._llm_verdict(active)
                active.summary = verdict.get("summary", active.summary) or active.summary
                active.direction = self._coerce_direction(
                    verdict.get("direction"), active.direction,
                )
                active.confidence = self._weighted_confidence(
                    active, verdict.get("confidence", active.confidence),
                )
                active.rationale = verdict.get("rationale", active.rationale) or active.rationale
                active.sentiment_arc = verdict.get("sentiment_arc") or active.sentiment_arc
                tf = verdict.get("timeframe")
                if tf in ("short_term", "medium_term"):
                    active.timeframe = Timeframe(tf)
                active.chunks_since_last_check.clear()
            except Exception:
                logger.exception(
                    "Final close-time LLM verdict failed (segment=%s); "
                    "closing with placeholder state",
                    active.segment_id,
                )

        snapshot = self._snapshot(active)
        snapshot.is_closed = True
        snapshot.end_time = datetime.now(UTC)
        snapshot.close_reason = reason
        try:
            from src.backtest import segment_log
            segment_log.append(snapshot)
        except Exception:
            logger.exception("Failed to persist segment %s", snapshot.segment_id)
        logger.info(
            "Segment closed: %s (commodity=%s, chunks=%d, direction=%s, reason=%s)",
            snapshot.segment_id, snapshot.primary_commodity,
            len(snapshot.chunk_ids), snapshot.direction.value, reason,
        )
        return ("close", snapshot)

    async def _apply_break_phrases(
        self, stream_id: str, chunk: _ChunkEntry,
    ) -> list[tuple[str, Segment]]:
        """Force-close segments on explicit break phrases in the transcript."""
        text = chunk.transcript_text.lower()
        if not any(phrase in text for phrase in BREAK_PHRASES):
            return []
        events: list[tuple[str, Segment]] = []
        for key, active in list(self._active.items()):
            if key[0] == stream_id:
                # Don't close a very fresh segment (< 2 chunks) — the phrase
                # may belong TO the segment, not end it.
                if len(active.all_chunks) < 2:
                    continue
                event = await self._close_segment(active, "break_phrase")
                events.append(event)
                del self._active[key]
        return events

    def _snapshot(self, active: _ActiveSegment) -> Segment:
        """Produce a Segment model from the current state of an active segment."""
        # Determine secondary commodities (mentioned >=1 time but not primary)
        secondary = [c for c, n in active.commodity_mention_count.items()
                     if c != active.primary_commodity and n >= 1]
        return Segment(
            segment_id=active.segment_id,
            stream_id=active.stream_id,
            primary_commodity=active.primary_commodity,
            secondary_commodities=sorted(secondary),
            start_time=active.start_time,
            end_time=None,
            chunk_ids=[c.chunk_id for c in active.all_chunks],
            summary=active.summary,
            direction=active.direction,
            confidence=round(active.confidence, 3),
            rationale=active.rationale,
            sentiment_arc=active.sentiment_arc,
            overall_timeframe=active.timeframe,
            is_closed=False,
            close_reason=None,
            reality_score=None,
        )

    def _weighted_confidence(self, active: _ActiveSegment, new_conf: Any) -> float:
        """Blend the current segment confidence with LLM's new estimate using
        exponential recency weighting across chunks."""
        try:
            new_val = float(new_conf)
        except (TypeError, ValueError):
            return active.confidence
        new_val = max(0.0, min(1.0, new_val))
        # Simple exponential moving average with aggressive weight on the latest verdict
        # (LLM has seen all chunks so its estimate is already an aggregate)
        if active.confidence == 0.0:
            return new_val
        half_life = max(0.1, self._config.recency_halflife_min)
        age_min = (datetime.now(UTC) - active.start_time).total_seconds() / 60.0
        decay = math.exp(-age_min * math.log(2) / half_life)
        return active.confidence * decay + new_val * (1 - decay)

    @staticmethod
    def _coerce_direction(value: Any, fallback: Direction) -> Direction:
        if not isinstance(value, str):
            return fallback
        val = value.lower()
        if val in ("bullish", "bearish", "neutral"):
            return Direction(val)
        if val == "mixed":
            return Direction.NEUTRAL  # Store mixed as neutral; arc field carries detail
        return fallback

    async def _llm_verdict(self, active: _ActiveSegment) -> dict[str, Any]:
        """Build the segment check prompt + parse LLM response."""
        # Build user message with full segment context
        chunks_desc = []
        for i, c in enumerate(active.all_chunks):
            marker = "  [NEW]" if c in active.chunks_since_last_check else ""
            chunks_desc.append(f"chunk #{i + 1}{marker} [{c.timestamp.strftime('%H:%M:%S')}]: "
                               f"{c.transcript_text[:400]}")
        chunks_text = "\n".join(chunks_desc)

        current_summary = active.summary or "(no summary yet — first check)"
        user_msg = (
            f"Primary commodity: {active.primary_commodity}\n"
            f"Segment started: {active.start_time.strftime('%H:%M:%S')}\n"
            f"Segment duration so far: {len(active.all_chunks)} chunks\n"
            f"Current summary: {current_summary}\n"
            f"Current direction: {active.direction.value} (confidence {active.confidence:.2f})\n\n"
            f"=== All chunks in this segment ===\n{chunks_text}\n\n"
            f"Return ONLY the JSON object (no markdown, no code fences)."
        )

        resp = await complete(
            self._client,
            self._provider,
            model=self._config.model,
            system=SEGMENT_SYSTEM_PROMPT,
            user=user_msg,
            max_tokens=512,
        )
        text = resp.text.strip()
        # Strip code fences if model added them
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```\s*$", "", text)
        return json.loads(text)
