from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import (
    AudioChunk,
    CommoditySignal,
    Direction,
    ExtractionResult,
    PipelineEvent,
    ScoringResult,
    Timeframe,
)


class TestAudioChunk:
    def test_valid(self):
        chunk = AudioChunk(
            chunk_id="abc123",
            source_url="test.wav",
            start_time=0.0,
            end_time=10.0,
            duration=10.0,
            audio_path="/tmp/test.wav",
        )
        assert chunk.sample_rate == 16_000
        assert chunk.chunk_id == "abc123"

    def test_created_at_auto(self):
        chunk = AudioChunk(
            chunk_id="abc",
            source_url="test.wav",
            start_time=0,
            end_time=10,
            duration=10,
            audio_path="/tmp/t.wav",
        )
        assert chunk.created_at is not None


class TestCommoditySignal:
    def test_valid_bullish(self):
        sig = CommoditySignal(
            commodity="crude_oil_wti",
            display_name="WTI Crude Oil",
            direction=Direction.BULLISH,
            confidence=0.85,
            rationale="Production cut reduces supply.",
            timeframe=Timeframe.SHORT_TERM,
            source_text="OPEC cut production",
        )
        assert sig.direction == Direction.BULLISH

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            CommoditySignal(
                commodity="gold",
                display_name="Gold",
                direction=Direction.BULLISH,
                confidence=1.5,  # out of bounds
                rationale="test",
                timeframe=Timeframe.SHORT_TERM,
                source_text="test",
            )

    def test_confidence_zero(self):
        sig = CommoditySignal(
            commodity="gold",
            display_name="Gold",
            direction=Direction.NEUTRAL,
            confidence=0.0,
            rationale="No signal",
            timeframe=Timeframe.SHORT_TERM,
            source_text="test",
        )
        assert sig.confidence == 0.0


class TestScoringResult:
    def test_empty_signals(self):
        result = ScoringResult(
            chunk_id="test",
            signals=[],
            model_used="test",
            input_tokens=0,
            output_tokens=0,
            processing_time_s=0.0,
        )
        assert len(result.signals) == 0

    def test_serialization(self, sample_extraction):
        """Verify ExtractionResult can be serialized/deserialized."""
        data = sample_extraction.model_dump()
        restored = ExtractionResult(**data)
        assert len(restored.commodities) == 2
        assert restored.commodities[0].name == "crude_oil_wti"


class TestPipelineEvent:
    def test_signal_event(self):
        scoring = ScoringResult(
            chunk_id="ch1",
            signals=[],
            model_used="test",
            input_tokens=0,
            output_tokens=0,
            processing_time_s=0.0,
        )
        event = PipelineEvent(
            event_type="signal",
            chunk_id="ch1",
            scoring=scoring,
        )
        assert event.event_type == "signal"
        json_str = event.model_dump_json()
        assert "ch1" in json_str
