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


class PipelineEvent(BaseModel):
    event_type: str  # "transcript" | "extraction" | "signal"
    chunk_id: str
    timestamp: datetime = Field(default_factory=_utcnow)
    transcript: Transcript | None = None
    extraction: ExtractionResult | None = None
    scoring: ScoringResult | None = None


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
