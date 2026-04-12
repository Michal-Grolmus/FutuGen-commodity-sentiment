"""Tests for Whisper transcriber with real audio files."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.stt.transcriber import Transcriber

SAMPLE_FILE = "audio_samples/sample_01_opec.wav"
REAL_FILE = "audio_samples/real/opec_raw.wav"


@pytest.fixture(scope="module")
def transcriber() -> Transcriber:
    return Transcriber(model_size="tiny", device="cpu", compute_type="int8", language="en")


@pytest.mark.asyncio
async def test_transcribe_tts_sample(transcriber):
    """Verify transcription of TTS-generated OPEC sample contains expected keywords."""
    if not Path(SAMPLE_FILE).exists():
        pytest.skip("TTS sample not generated")

    from src.ingestion.file_ingestor import FileIngestor

    ingestor = FileIngestor(SAMPLE_FILE, chunk_duration_s=15)
    async for chunk in ingestor.chunks():
        transcript = await transcriber.transcribe(chunk)
        text = transcript.full_text.lower()
        assert transcript.language == "en"
        assert transcript.language_probability > 0.8
        assert "opec" in text
        assert "production" in text or "barrel" in text
        assert transcript.processing_time_s < chunk.duration * 3  # must be under 3x
        assert len(transcript.segments) > 0
        break
    await ingestor.close()


@pytest.mark.asyncio
async def test_transcribe_real_audio(transcriber):
    """Verify transcription quality on real Bloomberg audio."""
    if not Path(REAL_FILE).exists():
        pytest.skip("Real audio not downloaded")

    from src.ingestion.file_ingestor import FileIngestor

    ingestor = FileIngestor(REAL_FILE, chunk_duration_s=15)
    async for chunk in ingestor.chunks():
        transcript = await transcriber.transcribe(chunk)
        text = transcript.full_text.lower()
        assert transcript.language == "en"
        assert transcript.language_probability > 0.8
        # Real Bloomberg audio should contain commodity keywords
        assert any(kw in text for kw in ["oil", "crude", "opec", "price", "market", "production"])
        assert transcript.processing_time_s < chunk.duration * 3
        break
    await ingestor.close()


@pytest.mark.asyncio
async def test_word_timestamps_present(transcriber):
    """Verify word-level timestamps are generated."""
    if not Path(SAMPLE_FILE).exists():
        pytest.skip("TTS sample not generated")

    from src.ingestion.file_ingestor import FileIngestor

    ingestor = FileIngestor(SAMPLE_FILE, chunk_duration_s=15)
    async for chunk in ingestor.chunks():
        transcript = await transcriber.transcribe(chunk)
        all_words = [w for seg in transcript.segments for w in seg.words]
        assert len(all_words) > 5
        for word in all_words[:5]:
            assert word.start >= 0
            assert word.end > word.start
            assert 0 <= word.probability <= 1
        break
    await ingestor.close()
