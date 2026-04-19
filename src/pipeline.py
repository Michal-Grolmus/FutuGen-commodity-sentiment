from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from src.analysis.entity_extractor import EntityExtractor
from src.analysis.impact_scorer import ImpactScorer
from src.analysis.segment_aggregator import SegmentAggregator, SegmentAggregatorConfig
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
        # scoring_q carries (transcript, scoring) so segment aggregator can see
        # the raw transcript text (needed for topic-change detection), not only signals.
        self._scoring_q: asyncio.Queue[tuple[Transcript, ScoringResult] | None] = (
            asyncio.Queue(maxsize=settings.max_queue_size)
        )

        # Components (initialized lazily in run)
        self._source: AudioSource | None = None
        self._transcriber: Transcriber | None = None
        self._extractor: EntityExtractor | None = None
        self._scorer: ImpactScorer | None = None
        self._aggregator: SegmentAggregator | None = None
        self._terminal: TerminalDisplay | None = None
        self._notifier: SlackNotifier | None = None
        self._price_client: PriceClient | None = None
        self._tmp_dirs: list[str] = []
        # For runtime start / restart from the dashboard
        self._run_task: asyncio.Task[None] | None = None

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

        # Bonus: Price tracking (also used as RAG context for scorer)
        if self._settings.enable_price_tracking:
            self._price_client = PriceClient()
            logger.info("Price tracking enabled (RAG context for scoring).")

        # Build analysis
        if self._settings.use_mock_analyzer:
            from src.analysis.mock_analyzer import MockExtractor, MockScorer
            self._extractor = MockExtractor()  # type: ignore[assignment]
            self._scorer = MockScorer()  # type: ignore[assignment]
            logger.info("Using mock analyzer (keyword-based, zero API cost).")
        elif self._build_analysis_layer():
            logger.info("Analysis layer active (provider=%s).", self._settings.llm_provider)
        else:
            logger.warning("No LLM API key — analysis layer disabled, transcription only.")

        # Bonus: Slack notifications
        if self._settings.slack_webhook_url:
            self._notifier = SlackNotifier(
                self._settings.slack_webhook_url,
                self._settings.notification_confidence_threshold,
            )
            logger.info(
                "Slack notifications enabled (threshold=%.1f)",
                self._settings.notification_confidence_threshold,
            )

        # Terminal display
        self._terminal = TerminalDisplay()

        logger.info("Pipeline starting...")

        try:
            from src.backtest.runner import run_loop as backtest_run_loop
            tasks = [
                asyncio.create_task(self._ingest_loop(), name="ingest"),
                asyncio.create_task(self._transcribe_loop(), name="transcribe"),
                asyncio.create_task(self._analyze_loop(), name="analyze"),
                asyncio.create_task(self._broadcast_loop(), name="broadcast"),
                asyncio.create_task(backtest_run_loop(), name="backtest"),
            ]
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._settings.pipeline_timeout_s,
            )
        except TimeoutError:
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
                else:
                    scoring = ScoringResult(
                        chunk_id=transcript.chunk_id,
                        signals=[],
                        model_used="none",
                        input_tokens=0,
                        output_tokens=0,
                        processing_time_s=0.0,
                    )

                await self._scoring_q.put((transcript, scoring))
            except Exception:
                logger.exception("Analysis error for chunk %s", transcript.chunk_id)

        await self._scoring_q.put(None)
        logger.info("Analysis finished.")

    async def _broadcast_loop(self) -> None:
        from src.backtest import signal_log
        stream_id = self._settings.input_file or self._settings.stream_url or "pipeline"
        while self._running:
            item = await self._scoring_q.get()
            if item is None:
                break
            transcript, result = item
            try:
                await self._broadcaster.publish(PipelineEvent(
                    event_type="signal",
                    chunk_id=result.chunk_id,
                    stream_id=stream_id,
                    scoring=result,
                ))
                if self._terminal:
                    self._terminal.update(result)

                # Persist each signal with price snapshot for delayed backtesting
                for sig in result.signals:
                    price_snapshot: float | None = None
                    if self._price_client is not None:
                        try:
                            price_snapshot = self._price_client.get_current_price(sig.commodity)
                        except Exception:
                            price_snapshot = None
                    try:
                        signal_log.append(
                            sig, stream_id=stream_id,
                            chunk_id=result.chunk_id,
                            price_snapshot=price_snapshot,
                        )
                    except Exception:
                        logger.exception("Failed to log signal %s", sig.commodity)

                # Bonus: send Slack notifications for high-confidence signals
                if self._notifier:
                    for sig in result.signals:
                        await self._notifier.notify_if_high_confidence(sig)

                # Segment aggregation: hierarchical super-events
                if self._aggregator is not None:
                    try:
                        seg_events = await self._aggregator.process_chunk(
                            stream_id, transcript, list(result.signals),
                        )
                        for kind, segment in seg_events:
                            await self._broadcaster.publish(PipelineEvent(
                                event_type=f"segment.{kind}",
                                chunk_id=result.chunk_id,
                                stream_id=stream_id,
                                segment=segment,
                            ))
                    except Exception:
                        logger.exception("Segment aggregation error for chunk %s",
                                         result.chunk_id)
            except Exception:
                logger.exception("Broadcast error for chunk %s", result.chunk_id)

        # Pipeline ending — close any open segments cleanly
        if self._aggregator is not None:
            try:
                closing = await self._aggregator.close_all("pipeline_stopped")
                for kind, segment in closing:
                    await self._broadcaster.publish(PipelineEvent(
                        event_type=f"segment.{kind}",
                        chunk_id=segment.segment_id,
                        stream_id=stream_id,
                        segment=segment,
                    ))
            except Exception:
                logger.exception("Error closing segments on shutdown")

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
        """Signal the pipeline to stop and cancel the run task.

        Safe to call whether the pipeline is running or idle.
        The run() coroutine will hit CancelledError, finally: _cleanup()
        will be invoked, which resets _running and kills subprocesses.
        """
        self._running = False
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()

    async def wait_stopped(self, timeout: float = 10.0) -> bool:
        """Await the run_task's completion after stop(). Returns True if
        it finished cleanly, False on timeout."""
        if self._run_task is None or self._run_task.done():
            return True
        try:
            await asyncio.wait_for(self._run_task, timeout=timeout)
            return True
        except (TimeoutError, asyncio.CancelledError):
            return False

    def is_running(self) -> bool:
        return self._running

    def start_with_source(self, source: str) -> dict[str, object]:
        """Attach a new source URL/file path and start the pipeline if idle.

        Called from the dashboard when the user clicks "Add Stream". Does not
        support restart while running — caller must stop first.
        Returns {"ok": bool, "started": bool, "reason": str}.
        """
        source = (source or "").strip()
        if not source:
            return {"ok": False, "started": False, "reason": "source is empty"}
        # Check both _running (set inside run()) AND _run_task (set before run()
        # is scheduled) to catch the race where two start calls arrive before
        # the event loop schedules the first run()'s first await.
        task_alive = self._run_task is not None and not self._run_task.done()
        if self._running or task_alive:
            return {"ok": False, "started": False,
                    "reason": "pipeline already running"}

        # Classify source: URL schemes → stream, otherwise → file path
        if source.startswith(("http://", "https://", "rtmp://", "rtmps://", "hls://")):
            self._settings.stream_url = source
            self._settings.input_file = ""
        else:
            self._settings.input_file = source
            self._settings.stream_url = ""

        # Rebuild queues — fresh state for the new run
        self._audio_q = asyncio.Queue(maxsize=self._settings.max_queue_size)
        self._transcript_q = asyncio.Queue(maxsize=self._settings.max_queue_size)
        self._scoring_q = asyncio.Queue(maxsize=self._settings.max_queue_size)

        self._run_task = asyncio.create_task(self.run(), name="pipeline-run")
        logger.info("Pipeline started with source: %s", source)
        return {"ok": True, "started": True, "reason": "launched"}

    def _build_analysis_layer(self) -> bool:
        """Instantiate extractor + scorer + segment aggregator using the
        configured provider. Returns True if a client was built, False otherwise.
        """
        provider = (self._settings.llm_provider or "anthropic").strip().lower()
        if provider == "openai":
            key = self._settings.openai_api_key
            if not key:
                return False
            client: AsyncAnthropic | AsyncOpenAI = AsyncOpenAI(api_key=key)
            ext_model = self._settings.openai_model_extraction
            score_model = self._settings.openai_model_scoring
        else:
            provider = "anthropic"
            key = self._settings.anthropic_api_key
            if not key:
                return False
            client = AsyncAnthropic(api_key=key)
            ext_model = self._settings.anthropic_model_extraction
            score_model = self._settings.anthropic_model_scoring

        self._extractor = EntityExtractor(client, ext_model, provider=provider)
        self._scorer = ImpactScorer(
            client, score_model, price_client=self._price_client, provider=provider,
        )
        self._aggregator = SegmentAggregator(
            client, provider=provider,
            config=SegmentAggregatorConfig(model=score_model),
        )
        return True

    def set_api_key(self, api_key: str, provider: str | None = None) -> bool:
        """Live-reload the LLM API key (and optionally switch provider).

        Rebuilds extractor and scorer with a new client. Existing in-flight
        calls keep the old client (safe). Next iteration uses the new one.
        Returns True if analysis layer is now active, False if key was empty.
        """
        api_key = (api_key or "").strip()
        if provider:
            self._settings.llm_provider = provider.strip().lower()
        active_provider = self._settings.llm_provider
        if active_provider == "openai":
            self._settings.openai_api_key = api_key
        else:
            self._settings.anthropic_api_key = api_key
        if not api_key:
            self._extractor = None
            self._scorer = None
            logger.info("API key cleared for provider=%s — analysis layer disabled.", active_provider)
            return False
        built = self._build_analysis_layer()
        if built:
            logger.info("API key updated — analysis layer active (provider=%s).", active_provider)
        return built
