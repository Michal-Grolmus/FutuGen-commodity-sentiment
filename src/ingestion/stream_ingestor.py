"""Ingests live HLS/RTMP/YouTube streams.

Dual backend (auto-selected at runtime):
  - **ffmpeg subprocess** (fast path, used when `ffmpeg` is on PATH)
    yt-dlp --get-url resolves the direct audio URL, ffmpeg reads it and pipes
    16 kHz mono s16le PCM back to Python. No Python-native pipe between
    subprocesses (works on Windows too).
  - **PyAV fallback** (pure-Python path, when ffmpeg binary is missing)
    Uses PyAV (already in dependencies for file ingestion) to open the
    resolved URL directly — libavformat handles HLS / HTTPS / RTMP natively.
    Decode+resample run in a background thread to keep the asyncio loop free.

Both backends share the same retry loop (30 min of retries), the same chunk
wrapping, and the same AudioChunk output.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import shutil
import tempfile
import threading
import uuid
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

import av

from src.ingestion.audio_source import AudioSource
from src.models import AudioChunk

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https", "rtmp", "rtmps", "hls"}

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
RETRY_DELAY_S = 5
MAX_RETRIES = 360  # 30 min of retries (meets "30+ minutes without failure" requirement)

# PyAV worker queue size: ~2 MB of PCM (≈60s buffer @ 16kHz mono s16)
PYAV_QUEUE_MAX = 200


class StreamIngestor(AudioSource):
    """Ingests live streams via ffmpeg (preferred) or PyAV (fallback)."""

    def __init__(self, url: str, chunk_duration_s: int = 10) -> None:
        self._validate_url(url)
        self._url = url
        self._chunk_duration_s = chunk_duration_s
        self._processes: list[asyncio.subprocess.Process] = []
        self._tmp_dir = tempfile.mkdtemp(prefix="csm_stream_")
        self._running = True
        self._ffmpeg_available = shutil.which("ffmpeg") is not None
        backend = "ffmpeg" if self._ffmpeg_available else "PyAV"
        logger.info("Stream ingestion backend: %s", backend)

    async def chunks(self) -> AsyncIterator[AudioChunk]:
        """Dispatch to the chosen backend. Retries up to MAX_RETRIES."""
        if self._ffmpeg_available:
            async for chunk in self._chunks_via_ffmpeg():
                yield chunk
        else:
            async for chunk in self._chunks_via_pyav():
                yield chunk

    # ------------------------------------------------------------------
    # Backend A: ffmpeg subprocess (when available)
    # ------------------------------------------------------------------
    async def _chunks_via_ffmpeg(self) -> AsyncIterator[AudioChunk]:
        chunk_bytes = SAMPLE_RATE * BYTES_PER_SAMPLE * self._chunk_duration_s
        chunk_index = 0
        retries = 0

        while self._running and retries < MAX_RETRIES:
            try:
                process = await self._start_ffmpeg()
                assert process.stdout is not None
                retries = 0
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
                logger.exception("Stream error (ffmpeg)")
            finally:
                await self._kill_processes()

            if self._running:
                retries += 1
                logger.info("Retry %d/%d in %ds...", retries, MAX_RETRIES, RETRY_DELAY_S)
                await asyncio.sleep(RETRY_DELAY_S)

    async def _resolve_direct_url(self) -> str:
        """yt-dlp --get-url (one-shot, no pipe). Falls back to original URL
        if yt-dlp isn't available or can't resolve (e.g. direct HLS URL)."""
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
            logger.warning("yt-dlp not installed; passing URL directly to decoder.")
        except Exception:
            logger.exception("yt-dlp error; falling back to original URL.")
        return self._url

    async def _start_ffmpeg(self) -> asyncio.subprocess.Process:
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
        except FileNotFoundError as e:  # pragma: no cover — guarded by _ffmpeg_available
            raise RuntimeError("ffmpeg binary vanished between init and launch") from e
        self._processes.append(ffmpeg)
        logger.info("Stream connected (ffmpeg): %s", self._url)
        return ffmpeg

    # ------------------------------------------------------------------
    # Backend B: PyAV (no ffmpeg binary needed)
    # ------------------------------------------------------------------
    async def _chunks_via_pyav(self) -> AsyncIterator[AudioChunk]:
        chunk_bytes = SAMPLE_RATE * BYTES_PER_SAMPLE * self._chunk_duration_s
        chunk_index = 0
        retries = 0

        while self._running and retries < MAX_RETRIES:
            stop_event = threading.Event()
            data_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=PYAV_QUEUE_MAX)
            thread: threading.Thread | None = None

            try:
                direct_url = await self._resolve_direct_url()
                thread = threading.Thread(
                    target=self._pyav_worker,
                    args=(direct_url, data_queue, stop_event),
                    name="pyav-decoder",
                    daemon=True,
                )
                thread.start()
                logger.info("Stream connected (PyAV): %s", self._url)
                retries = 0
                buffer = b""

                while self._running:
                    try:
                        data = await asyncio.wait_for(
                            asyncio.to_thread(data_queue.get),
                            timeout=30.0,
                        )
                    except TimeoutError:
                        logger.warning("PyAV stream read timeout, reconnecting...")
                        break

                    if data is None:
                        logger.warning("Stream ended, will retry...")
                        break

                    buffer += data
                    while len(buffer) >= chunk_bytes:
                        yield self._make_chunk(buffer[:chunk_bytes], chunk_index)
                        buffer = buffer[chunk_bytes:]
                        chunk_index += 1

            except Exception:
                logger.exception("Stream error (PyAV)")
            finally:
                stop_event.set()
                if thread is not None and thread.is_alive():
                    thread.join(timeout=2.0)

            if self._running:
                retries += 1
                logger.info("Retry %d/%d in %ds...", retries, MAX_RETRIES, RETRY_DELAY_S)
                await asyncio.sleep(RETRY_DELAY_S)

    @staticmethod
    def _pyav_worker(
        url: str,
        data_queue: queue.Queue[bytes | None],
        stop_event: threading.Event,
    ) -> None:
        """Runs in a thread. Opens the stream with libavformat, decodes audio,
        resamples to 16 kHz mono s16le, and pushes PCM bytes onto the queue.
        Always terminates by pushing a final None marker."""
        try:
            # Reconnect / timeout options forwarded to libavformat
            options = {
                "reconnect": "1",
                "reconnect_streamed": "1",
                "reconnect_delay_max": "5",
                "timeout": "10000000",  # microseconds → 10 s
            }
            container = av.open(url, options=options)
            audio_stream = next(
                (s for s in container.streams if s.type == "audio"), None,
            )
            if audio_stream is None:
                logger.error("No audio stream found in source.")
                return
            resampler = av.AudioResampler(
                format="s16", layout="mono", rate=SAMPLE_RATE,
            )
            for packet in container.demux(audio_stream):
                if stop_event.is_set():
                    break
                for frame in packet.decode():
                    if stop_event.is_set():
                        break
                    for rframe in resampler.resample(frame):
                        # rframe.to_ndarray() works across PyAV 10+ for all formats
                        pcm = rframe.to_ndarray().tobytes()
                        while not stop_event.is_set():
                            try:
                                data_queue.put(pcm, timeout=1.0)
                                break
                            except queue.Full:
                                continue
            container.close()
        except Exception:
            logger.exception("PyAV worker error")
        finally:
            try:
                data_queue.put_nowait(None)
            except queue.Full:
                # Queue is full — dropping EOF marker is fine, caller's 30s
                # read-timeout will trigger reconnect on the next iteration.
                pass

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
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
