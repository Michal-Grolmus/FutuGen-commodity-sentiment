from __future__ import annotations

import enum
from datetime import UTC, datetime

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AudioChunk(BaseModel):
    chunk_id: str
    source_url: str
    start_time: float
    end_time: float
    duration: float
    sample_rate: int = 16_000
    audio_path: str
    created_at: datetime = Field(default_factory=_utcnow)


class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float
    probability: float


class TranscriptSegment(BaseModel):
    segment_id: int
    start: float
    end: float
    text: str
    words: list[WordTimestamp]
    avg_logprob: float
    no_speech_prob: float


class Transcript(BaseModel):
    chunk_id: str
    source_url: str = ""  # originating stream URL or file path (for multi-source routing)
    language: str
    language_probability: float
    segments: list[TranscriptSegment]
    full_text: str
    processing_time_s: float
    created_at: datetime = Field(default_factory=_utcnow)


class CommodityMention(BaseModel):
    name: str  # canonical e.g. "crude_oil_wti"
    display_name: str  # e.g. "WTI Crude Oil"
    context: str


class PersonMention(BaseModel):
    name: str
    role: str | None = None
    context: str


class EconomicIndicator(BaseModel):
    name: str
    display_name: str
    context: str


class ExtractionResult(BaseModel):
    chunk_id: str
    commodities: list[CommodityMention]
    people: list[PersonMention]
    indicators: list[EconomicIndicator]
    raw_text: str
    model_used: str
    input_tokens: int
    output_tokens: int
    processing_time_s: float
    created_at: datetime = Field(default_factory=_utcnow)


class Direction(str, enum.Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Timeframe(str, enum.Enum):
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"


class CommoditySignal(BaseModel):
    commodity: str
    display_name: str
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    timeframe: Timeframe
    source_text: str
    speaker: str | None = None


class ScoringResult(BaseModel):
    chunk_id: str
    signals: list[CommoditySignal]
    model_used: str
    input_tokens: int
    output_tokens: int
    processing_time_s: float
    created_at: datetime = Field(default_factory=_utcnow)


class Segment(BaseModel):
    """A 'super-event' — coherent block of commodity discussion spanning 60+s.

    Built from N individual chunks by SegmentAggregator. The aggregator calls
    LLM every `check_interval_chunks` (default 6 = 60s at 10s chunks) to decide
    if the topic continues or has shifted. At close, a reality_score is fetched
    asynchronously (t0 price vs +1m/+5m/+15m/+1h).
    """
    segment_id: str
    stream_id: str
    primary_commodity: str
    secondary_commodities: list[str] = Field(default_factory=list)
    start_time: datetime
    end_time: datetime | None = None  # None = still active

    # Built incrementally per check interval
    chunk_ids: list[str] = Field(default_factory=list)

    # Current (or final) LLM verdict
    summary: str = ""
    direction: Direction = Direction.NEUTRAL
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    sentiment_arc: str | None = None  # "opened bullish, closed bearish" for mixed segments
    overall_timeframe: Timeframe = Timeframe.SHORT_TERM

    # State
    is_closed: bool = False
    close_reason: str | None = None  # "topic_shift" | "hard_cap" | "stream_removed" | "break_phrase"

    # Filled by reality scorer after close (not immediately)
    reality_score: dict | None = None


class PipelineEvent(BaseModel):
    # Event types: "transcript" | "extraction" | "signal" | "segment"
    # For segments, the segment field carries open/update/close state via is_closed.
    event_type: str
    chunk_id: str
    stream_id: str | None = None  # explicit per-stream routing (new)
    timestamp: datetime = Field(default_factory=_utcnow)
    transcript: Transcript | None = None
    extraction: ExtractionResult | None = None
    scoring: ScoringResult | None = None
    segment: Segment | None = None


# --- Evaluation ---


class GroundTruthLabel(BaseModel):
    excerpt_id: str
    audio_file: str
    description: str
    transcript_text: str
    expected_commodities: list[str]
    expected_direction: Direction
    expected_timeframe: Timeframe
    rationale: str


class EvalPrediction(BaseModel):
    excerpt_id: str
    predicted_signals: list[CommoditySignal]
    ground_truth: GroundTruthLabel
    direction_correct: bool
    commodity_recall: float
