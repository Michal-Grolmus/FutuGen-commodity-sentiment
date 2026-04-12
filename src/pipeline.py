from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic

from src.analysis.entity_extractor import EntityExtractor
from src.analysis.impact_scorer import ImpactScorer
from src.config import Settings
from src.dashboard.server import SignalBroadcaster
from src.dashboard.terminal import TerminalDisplay
from src.ingestion.file_ingestor import FileIngestor
from src.ingestion.stream_ingestor import StreamIngestor
from src.models import AudioChunk, PipelineEvent, ScoringResult, Transcript
from src.notifications.webhook import SlackNotifier
from src.prices.yahoo_client import PriceClient
from src.stt.transcriber import Transcriber

if TYPE_CHECKING:
    from src.ingestion.audio_source import AudioSource

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        broadcaster: SignalBroadcaster,
    ) -> None:
        self._settings = settings
        self._broadcaster = broadcaster
        self._running = False

        # Queues
        self._audio_q: asyncio.Queue[AudioChunk | None] = asyncio.Queue(
            maxsize=settings.max_queue_size
        )
        self._transcript_q: asyncio.Queue[Transcript | None] = asyncio.Queue(
            maxsize=settings.max_queue_size
        )
        self._scoring_q: asyncio.Queue[ScoringResult | None] = asyncio.Queue(
            maxsize=settings.max_queue_size
        )

        # Components (initialized lazily in run)
        self._source: AudioSource | None = None
        self._transcriber: Transcriber | None = None
        self._extractor: EntityExtractor | None = None
        self._scorer: ImpactScorer | None = None
        self._terminal: TerminalDisplay | None = None
        self._notifier: SlackNotifier | None = None
        self._price_client: PriceClient | None = None
        self._tmp_dirs: list[str] = []

    async def run(self) -> None:
        self._running = True

        # Build audio source
        if self._settings.input_file:
            self._source = FileIngestor(self._settings.input_file, self._settings.chunk_duration_s)
            logger.info("Using file source: %s", self._settings.input_file)
        elif self._settings.stream_url:
            self._source = StreamIngestor(self._settings.stream_url, self._settings.chunk_duration_s)
            logger.info("Using stream source: %s", self._settings.stream_url)
        else:
            logger.error("No input source configured. Set INPUT_FILE or STREAM_URL.")
            return

        # Build STT
        self._transcriber = Transcriber(
            model_size=self._settings.whisper_model_size,
            device=self._settings.whisper_device,
            compute_type=self._settings.whisper_compute_type,
            language=self._settings.whisper_language or None,
        )

        # Build analysis (requires API key)
        if self._settings.anthropic_api_key:
            client = AsyncAnthropic(api_key=self._settings.anthropic_api_key)
            self._extractor = EntityExtractor(client, self._settings.anthropic_model_extraction)
            self._scorer = ImpactScorer(client, self._settings.anthropic_model_scoring)
        else:
            logger.warning("No ANTHROPIC_API_KEY — analysis layer disabled, transcription only.")

        # Bonus: Slack notifications
        if self._settings.slack_webhook_url:
            self._notifier = SlackNotifier(
                self._settings.slack_webhook_url,
                self._settings.notification_confidence_threshold,
            )
            logger.info("Slack notifications enabled (threshold=%.1f)", self._settings.notification_confidence_threshold)

        # Bonus: Price tracking
        if self._settings.enable_price_tracking:
            self._price_client = PriceClient()
            logger.info("Historical price tracking enabled.")

        # Terminal display
        self._terminal = TerminalDisplay()

        logger.info("Pipeline starting...")

        try:
            tasks = [
                asyncio.create_task(self._ingest_loop(), name="ingest"),
                asyncio.create_task(self._transcribe_loop(), name="transcribe"),
                asyncio.create_task(self._analyze_loop(), name="analyze"),
                asyncio.create_task(self._broadcast_loop(), name="broadcast"),
            ]
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._settings.pipeline_timeout_s,
            )
        except asyncio.TimeoutError:
            logger.info("Pipeline timeout reached (%ds).", self._settings.pipeline_timeout_s)
        except asyncio.CancelledError:
            logger.info("Pipeline cancelled.")
        finally:
            await self._cleanup()

    async def _ingest_loop(self) -> None:
        assert self._source is not None
        try:
            async for chunk in self._source.chunks():
                if not self._running:
                    break
                # Track temp dirs for cleanup
                tmp_dir = str(Path(chunk.audio_path).parent)
                if tmp_dir not in self._tmp_dirs:
                    self._tmp_dirs.append(tmp_dir)
                await self._audio_q.put(chunk)
        except Exception:
            logger.exception("Ingestion error")
        finally:
            await self._audio_q.put(None)
            logger.info("Ingestion finished.")

    async def _transcribe_loop(self) -> None:
        assert self._transcriber is not None
        while self._running:
            chunk = await self._audio_q.get()
            if chunk is None:
                break
            try:
                transcript = await self._transcriber.transcribe(chunk)
                # Clean up processed chunk file
                try:
                    Path(chunk.audio_path).unlink(missing_ok=True)
                except OSError:
                    pass
                # Filter: skip empty or low-confidence transcripts
                if (
                    transcript.full_text.strip()
                    and transcript.language_probability >= 0.5
                    and len(transcript.full_text.split()) >= 3
                ):
                    await self._transcript_q.put(transcript)
                    await self._broadcaster.publish(PipelineEvent(
                        event_type="transcript",
                        chunk_id=chunk.chunk_id,
                        transcript=transcript,
                    ))
            except Exception:
                logger.exception("Transcription error for chunk %s", chunk.chunk_id)

        await self._transcript_q.put(None)
        logger.info("Transcription finished.")

    async def _analyze_loop(self) -> None:
        while self._running:
            transcript = await self._transcript_q.get()
            if transcript is None:
                break
            try:
                if self._extractor and self._scorer:
                    extraction = await self._extractor.extract(transcript)
                    await self._broadcaster.publish(PipelineEvent(
                        event_type="extraction",
                        chunk_id=transcript.chunk_id,
                        extraction=extraction,
                    ))

                    scoring = await self._scorer.score(extraction)

                    # Bonus: enrich signals with current price data
                    if self._price_client:
                        for sig in scoring.signals:
                            price = self._price_client.get_current_price(sig.commodity)
                            if price is not None:
                                sig.rationale += f" (current price: ${price:.2f})"
                else:
                    scoring = ScoringResult(
                        chunk_id=transcript.chunk_id,
                        signals=[],
                        model_used="none",
                        input_tokens=0,
                        output_tokens=0,
                        processing_time_s=0.0,
                    )

                await self._scoring_q.put(scoring)
            except Exception:
                logger.exception("Analysis error for chunk %s", transcript.chunk_id)

        await self._scoring_q.put(None)
        logger.info("Analysis finished.")

    async def _broadcast_loop(self) -> None:
        while self._running:
            result = await self._scoring_q.get()
            if result is None:
                break
            try:
                await self._broadcaster.publish(PipelineEvent(
                    event_type="signal",
                    chunk_id=result.chunk_id,
                    scoring=result,
                ))
                if self._terminal:
                    self._terminal.update(result)

                # Bonus: send Slack notifications for high-confidence signals
                if self._notifier:
                    for sig in result.signals:
                        await self._notifier.notify_if_high_confidence(sig)
            except Exception:
                logger.exception("Broadcast error for chunk %s", result.chunk_id)

        logger.info("Broadcast finished.")

    async def _cleanup(self) -> None:
        """Clean up resources on shutdown."""
        self._running = False
        if self._source:
            await self._source.close()
        if self._notifier:
            await self._notifier.close()
        # Clean up temp directories
        for tmp_dir in self._tmp_dirs:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except OSError:
                pass
        logger.info("Pipeline stopped and cleaned up.")

    def stop(self) -> None:
        self._running = False
