from __future__ import annotations

import asyncio
import logging
import time
from functools import partial

from faster_whisper import WhisperModel

from src.models import AudioChunk, Transcript, TranscriptSegment, WordTimestamp

logger = logging.getLogger(__name__)


class Transcriber:
    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        logger.info("Loading Whisper model: %s (device=%s, compute=%s)", model_size, device, compute_type)
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info("Whisper model loaded.")

    async def transcribe(self, chunk: AudioChunk) -> Transcript:
        """Transcribe an audio chunk. Runs in executor to avoid blocking the event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._transcribe_sync, chunk))

    def _transcribe_sync(self, chunk: AudioChunk) -> Transcript:
        t0 = time.perf_counter()

        segments_iter, info = self._model.transcribe(
            chunk.audio_path,
            word_timestamps=True,
            vad_filter=True,
        )

        segments: list[TranscriptSegment] = []
        full_parts: list[str] = []

        for i, seg in enumerate(segments_iter):
            words = [
                WordTimestamp(
                    word=w.word.strip(),
                    start=w.start,
                    end=w.end,
                    probability=w.probability,
                )
                for w in (seg.words or [])
            ]
            segments.append(TranscriptSegment(
                segment_id=i,
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                words=words,
                avg_logprob=seg.avg_logprob,
                no_speech_prob=seg.no_speech_prob,
            ))
            full_parts.append(seg.text.strip())

        elapsed = time.perf_counter() - t0
        full_text = " ".join(full_parts)

        logger.info(
            "Chunk %s transcribed in %.2fs (%.1fx real-time): %s",
            chunk.chunk_id, elapsed, elapsed / max(chunk.duration, 0.01),
            full_text[:100],
        )

        return Transcript(
            chunk_id=chunk.chunk_id,
            language=info.language,
            language_probability=info.language_probability,
            segments=segments,
            full_text=full_text,
            processing_time_s=elapsed,
        )
