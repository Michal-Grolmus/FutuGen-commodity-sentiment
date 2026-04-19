from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

from src.ingestion.audio_source import AudioSource
from src.models import AudioChunk

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https", "rtmp", "rtmps", "hls"}

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
RETRY_DELAY_S = 5
MAX_RETRIES = 360  # 30 min of retries (meets "30+ minutes without failure" requirement)


class StreamIngestor(AudioSource):
    """Ingests live HLS/RTMP/YouTube streams via yt-dlp piped to ffmpeg."""

    def __init__(self, url: str, chunk_duration_s: int = 10) -> None:
        self._validate_url(url)
        self._url = url
        self._chunk_duration_s = chunk_duration_s
        self._processes: list[asyncio.subprocess.Process] = []
        self._tmp_dir = tempfile.mkdtemp(prefix="csm_stream_")
        self._running = True

    async def chunks(self) -> AsyncIterator[AudioChunk]:
        chunk_bytes = SAMPLE_RATE * BYTES_PER_SAMPLE * self._chunk_duration_s
        chunk_index = 0
        retries = 0

        while self._running and retries < MAX_RETRIES:
            try:
                process = await self._start_stream()
                assert process.stdout is not None
                retries = 0  # reset on successful connect
                buffer = b""

                while self._running:
                    data = await asyncio.wait_for(
                        process.stdout.read(chunk_bytes - len(buffer)),
                        timeout=30.0,
                    )
                    if not data:
                        logger.warning("Stream ended, will retry...")
                        break

                    buffer += data
                    if len(buffer) >= chunk_bytes:
                        yield self._make_chunk(buffer[:chunk_bytes], chunk_index)
                        buffer = buffer[chunk_bytes:]
                        chunk_index += 1

            except TimeoutError:
                logger.warning("Stream read timeout, reconnecting...")
            except Exception:
                logger.exception("Stream error")
            finally:
                await self._kill_processes()

            if self._running:
                retries += 1
                logger.info("Retry %d/%d in %ds...", retries, MAX_RETRIES, RETRY_DELAY_S)
                await asyncio.sleep(RETRY_DELAY_S)

    async def _resolve_direct_url(self) -> str:
        """Use yt-dlp to resolve a direct audio URL (HLS / HTTPS / RTMP).

        One-shot call (not piped) — avoids Windows asyncio pipe-between-subprocess
        bug. Falls back to the original URL if yt-dlp fails or isn't needed
        (direct HLS/RTMP URLs work with ffmpeg without yt-dlp).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--no-warnings", "-f", "bestaudio/best",
                "--get-url", self._url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            if proc.returncode == 0 and stdout:
                url = stdout.decode().strip().split("\n")[0]
                if url:
                    logger.info("yt-dlp resolved direct URL (%d chars).", len(url))
                    return url
            err_text = (stderr or b"").decode(errors="ignore")[:200]
            logger.warning("yt-dlp could not resolve (%d): %s", proc.returncode, err_text)
        except FileNotFoundError:
            logger.warning("yt-dlp not installed; passing URL directly to ffmpeg.")
        except Exception:
            logger.exception("yt-dlp error; falling back to original URL.")
        return self._url

    async def _start_stream(self) -> asyncio.subprocess.Process:
        # Resolve via yt-dlp first (YouTube/Twitch/etc.), then let ffmpeg read
        # the direct URL. Pipe-between-subprocesses is not used because on
        # Windows, asyncio cannot use a StreamReader as another subprocess'
        # stdin (no fileno()).
        direct_url = await self._resolve_direct_url()
        try:
            ffmpeg = await asyncio.create_subprocess_exec(
                "ffmpeg", "-i", direct_url,
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ar", str(SAMPLE_RATE), "-ac", "1",
                "-loglevel", "error",
                "pipe:1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "ffmpeg binary not found on PATH. Install ffmpeg "
                "(https://ffmpeg.org/download.html) to process live streams. "
                "File-based sources work without ffmpeg (via PyAV)."
            ) from e
        self._processes.append(ffmpeg)
        logger.info("Stream connected: %s", self._url)
        return ffmpeg

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

        return AudioChunk(
            chunk_id=chunk_id,
            source_url=self._url,
            start_time=start_time,
            end_time=start_time + duration,
            duration=duration,
            sample_rate=SAMPLE_RATE,
            audio_path=wav_path,
        )

    async def _kill_processes(self) -> None:
        for proc in self._processes:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        self._processes.clear()

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ALLOWED_SCHEMES and not url.startswith("https://www.youtube.com"):
            raise ValueError(f"Invalid stream URL scheme: {parsed.scheme!r}. Allowed: {ALLOWED_SCHEMES}")
        if not parsed.netloc:
            raise ValueError("Stream URL must have a valid hostname.")

    async def close(self) -> None:
        self._running = False
        await self._kill_processes()
