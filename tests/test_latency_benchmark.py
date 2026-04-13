"""Latency benchmark: proves pipeline meets the <3x real-time requirement."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.ingestion.file_ingestor import FileIngestor
from src.stt.transcriber import Transcriber

SAMPLE_FILE = "audio_samples/sample_01_opec.wav"
REAL_FILE = "audio_samples/real/opec_raw.wav"

# Assignment requirement: latency < 3x chunk duration
MAX_LATENCY_RATIO = 3.0


@pytest.fixture(scope="module")
def transcriber() -> Transcriber:
    return Transcriber(model_size="tiny", device="cpu", compute_type="int8", language="en")


@pytest.mark.asyncio
async def test_stt_latency_under_3x_tts(transcriber):
    """STT latency must be under 3x chunk duration on TTS audio."""
    if not Path(SAMPLE_FILE).exists():
        pytest.skip("Sample not available")

    ingestor = FileIngestor(SAMPLE_FILE, chunk_duration_s=10)
    latency_ratios = []

    async for chunk in ingestor.chunks():
        transcript = await transcriber.transcribe(chunk)
        ratio = transcript.processing_time_s / chunk.duration
        latency_ratios.append(ratio)
        assert ratio < MAX_LATENCY_RATIO, (
            f"STT latency {transcript.processing_time_s:.2f}s is "
            f"{ratio:.1f}x chunk duration ({chunk.duration:.1f}s) — exceeds {MAX_LATENCY_RATIO}x limit"
        )

    await ingestor.close()
    avg_ratio = sum(latency_ratios) / len(latency_ratios)
    print(f"\nLatency benchmark: avg={avg_ratio:.2f}x, max={max(latency_ratios):.2f}x (limit: {MAX_LATENCY_RATIO}x)")


@pytest.mark.asyncio
async def test_stt_latency_under_3x_real(transcriber):
    """STT latency must be under 3x chunk duration on real Bloomberg audio."""
    if not Path(REAL_FILE).exists():
        pytest.skip("Real audio not available")

    ingestor = FileIngestor(REAL_FILE, chunk_duration_s=10)
    latency_ratios = []

    async for chunk in ingestor.chunks():
        transcript = await transcriber.transcribe(chunk)
        ratio = transcript.processing_time_s / chunk.duration
        latency_ratios.append(ratio)
        assert ratio < MAX_LATENCY_RATIO

    await ingestor.close()
    avg_ratio = sum(latency_ratios) / len(latency_ratios)
    print(f"\nReal audio benchmark: avg={avg_ratio:.2f}x, max={max(latency_ratios):.2f}x (limit: {MAX_LATENCY_RATIO}x)")
