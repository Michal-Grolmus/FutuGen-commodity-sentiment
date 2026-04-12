from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
import wave
from collections.abc import AsyncIterator
from functools import partial
from pathlib import Path

import av

from src.ingestion.audio_source import AudioSource
from src.models import AudioChunk

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2  # 16-bit PCM


class FileIngestor(AudioSource):
    """Reads a local audio file and yields it as fixed-duration chunks.

    Uses PyAV for decoding (no ffmpeg binary required).
    """

    def __init__(self, file_path: str, chunk_duration_s: int = 10) -> None:
        self._file_path = file_path
        self._chunk_duration_s = chunk_duration_s
        self._tmp_dir = tempfile.mkdtemp(prefix="csm_chunks_")

    async def chunks(self) -> AsyncIterator[AudioChunk]:
        loop = asyncio.get_running_loop()
        pcm_data = await loop.run_in_executor(None, partial(self._decode_to_pcm))

        chunk_bytes = SAMPLE_RATE * BYTES_PER_SAMPLE * self._chunk_duration_s
        chunk_index = 0
        offset = 0

        while offset < len(pcm_data):
            end = offset + chunk_bytes
            segment = pcm_data[offset:end]

            # Skip very short tail segments
            if len(segment) < chunk_bytes // 4:
                break

            yield self._make_chunk(segment, chunk_index)
            chunk_index += 1
            offset = end

    def _decode_to_pcm(self) -> bytes:
        """Decode audio file to 16kHz mono s16le PCM using PyAV."""
        container = av.open(self._file_path)
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

        pcm_data = b""
        for frame in container.decode(audio=0):
            resampled = resampler.resample(frame)
            for r in resampled:
                pcm_data += bytes(r.planes[0])

        container.close()
        return pcm_data

    def _make_chunk(self, pcm_data: bytes, index: int) -> AudioChunk:
        chunk_id = uuid.uuid4().hex[:12]
        start_time = index * self._chunk_duration_s
        duration = len(pcm_data) / (SAMPLE_RATE * BYTES_PER_SAMPLE)
        wav_path = str(Path(self._tmp_dir) / f"chunk_{chunk_id}.wav")

        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(BYTES_PER_SAMPLE)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm_data)

        logger.info("Chunk %s: %.1fs-%.1fs (%s)", chunk_id, start_time, start_time + duration, wav_path)
        return AudioChunk(
            chunk_id=chunk_id,
            source_url=self._file_path,
            start_time=start_time,
            end_time=start_time + duration,
            duration=duration,
            sample_rate=SAMPLE_RATE,
            audio_path=wav_path,
        )

    async def close(self) -> None:
        pass  # No subprocess to kill with PyAV
