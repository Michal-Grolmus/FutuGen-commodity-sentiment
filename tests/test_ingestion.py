from __future__ import annotations

from pathlib import Path

import pytest

from src.ingestion.file_ingestor import FileIngestor

SAMPLE_FILE = "audio_samples/sample_01_opec.wav"


@pytest.mark.asyncio
async def test_file_ingestor_yields_chunks():
    if not Path(SAMPLE_FILE).exists():
        pytest.skip("Audio sample not generated yet")

    ingestor = FileIngestor(SAMPLE_FILE, chunk_duration_s=10)
    chunks = []
    async for chunk in ingestor.chunks():
        chunks.append(chunk)
        assert chunk.duration > 0
        assert chunk.sample_rate == 16_000
        assert Path(chunk.audio_path).exists()

    assert len(chunks) >= 1
    await ingestor.close()


@pytest.mark.asyncio
async def test_file_ingestor_chunk_duration():
    if not Path(SAMPLE_FILE).exists():
        pytest.skip("Audio sample not generated yet")

    ingestor = FileIngestor(SAMPLE_FILE, chunk_duration_s=5)
    chunks = []
    async for chunk in ingestor.chunks():
        chunks.append(chunk)

    # With 5s chunks from ~21s audio, expect 4 chunks
    assert len(chunks) >= 3
    # First chunk should be ~5 seconds
    assert abs(chunks[0].duration - 5.0) < 0.5
    await ingestor.close()
