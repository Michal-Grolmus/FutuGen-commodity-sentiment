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
        # Workers alive? Set True once _start_workers runs, False after drain.
        self._running = False

        # Queues — shared by all sources. Created once and reused across
        # add_source / remove_source cycles.
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

        # Components (initialized lazily by _start_workers)
        self._transcriber: Transcriber | None = None
        self._extractor: EntityExtractor | None = None
        self._scorer: ImpactScorer | None = None
        self._aggregator: SegmentAggregator | None = None
        self._terminal: TerminalDisplay | None = None
        self._notifier: SlackNotifier | None = None
        self._price_client: PriceClient | None = None
        self._tmp_dirs: list[str] = []

        # Multi-source support: every active stream/file has its own ingest
        # task pushing chunks into the shared _audio_q. Map: url -> (source, task)
        self._sources: dict[str, tuple[AudioSource, asyncio.Task[None]]] = {}
        # Shared worker tasks (transcribe/analyze/broadcast + backtest runners)
        self._worker_tasks: list[asyncio.Task[None]] = []
        # Legacy: the task created by run() for the blocking one-shot path.
        self._run_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Shared-worker startup (idempotent; called by run() and add_source())
    # ------------------------------------------------------------------
    async def _start_workers(self) -> None:
        """Initialize transcribe/analyze/broadcast workers (idempotent).

        The shared workers stay alive while any source is active, or until
        stop() signals full shutdown. Individual sources come and go via
        add_source() / remove_source() without touching the workers.
        """
        if self._running:
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

        self._terminal = TerminalDisplay()

        from src.backtest import segment_reality
        from src.backtest.runner import run_loop as backtest_run_loop
        segment_reality.ensure_queue()

        self._running = True
        self._worker_tasks = [
            asyncio.create_task(self._transcribe_loop(), name="transcribe"),
            asyncio.create_task(self._analyze_loop(), name="analyze"),
            asyncio.create_task(self._broadcast_loop(), name="broadcast"),
            asyncio.create_task(backtest_run_loop(), name="backtest"),
            asyncio.create_task(segment_reality.run_worker(), name="segment-reality"),
        ]
        logger.info("Pipeline workers started.")

    # ------------------------------------------------------------------
    # Source lifecycle (multi-stream support)
    # ------------------------------------------------------------------
    async def add_source(self, url: str) -> dict[str, object]:
        """Add a new source (URL or file path) to the running pipeline.

        Starts the shared workers if not yet running. Returns immediately —
        the ingest task runs in the background and pushes chunks onto the
        shared queue as they're produced.
        """
        url = (url or "").strip()
        if not url:
            return {"ok": False, "started": False, "reason": "source is empty"}
        if url in self._sources:
            return {"ok": True, "started": False, "reason": "already active"}

        # Build the right source type
        if url.startswith(("http://", "https://", "rtmp://", "rtmps://", "hls://")):
            source: AudioSource = StreamIngestor(url, self._settings.chunk_duration_s)
            logger.info("Adding stream source: %s", url)
        else:
            source = FileIngestor(url, self._settings.chunk_duration_s)
            logger.info("Adding file source: %s", url)

        # Make sure the shared workers are alive
        await self._start_workers()

        task = asyncio.create_task(
            self._ingest_from_source(url, source),
            name=f"ingest:{url[:60]}",
        )
        self._sources[url] = (source, task)
        return {"ok": True, "started": True, "reason": "launched"}

    async def remove_source(self, url: str) -> dict[str, object]:
        """Stop a specific source without affecting others.

        Cancels its ingest task, closes the AudioSource, and removes it from
        the active set. Workers keep running for remaining sources.
        """
        entry = self._sources.pop(url, None)
        if entry is None:
            return {"ok": False, "reason": "not active"}
        source, task = entry
        task.cancel()
        try:
            await source.close()
        except Exception:
            logger.exception("Error closing source %s", url)
        logger.info("Removed source: %s", url)
        return {"ok": True}

    def active_sources(self) -> list[str]:
        """List URLs of all currently active sources."""
        return list(self._sources.keys())

    # Legacy alias kept so the dashboard server keeps compiling; now an
    # additive operation, not a swap.
    def start_with_source(self, source: str) -> dict[str, object]:
        """Additive: schedule a new source. Does NOT replace existing ones.

        For backward compat with the dashboard/server API. The actual work
        happens in add_source() which is invoked as a background task so this
        method remains synchronous (matches the old signature).
        """
        source = (source or "").strip()
        if not source:
            return {"ok": False, "started": False, "reason": "source is empty"}
        if source in self._sources:
            return {"ok": True, "started": False, "reason": "already active"}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return {"ok": False, "started": False, "reason": "no running loop"}
        # Kick off add_source in the background; the HTTP handler returns
        # immediately and the UI gets progress via SSE.
        loop.create_task(self.add_source(source), name=f"add_source:{source[:40]}")
        return {"ok": True, "started": True, "reason": "launched"}

    # ------------------------------------------------------------------
    # run(): legacy blocking entry point for CLI and tests
    # ------------------------------------------------------------------
    async def run(self) -> None:
        """One-shot blocking run of a single configured source.

        Reads input_file or stream_url from settings, adds it as a source,
        waits for it to finish (or the pipeline_timeout_s cap), then tears
        everything down. Preserves the single-source semantics expected by
        CLI + integration tests — dashboard uses add_source() instead.
        """
        initial = self._settings.input_file or self._settings.stream_url
        if not initial:
            logger.error("No input source configured. Set INPUT_FILE or STREAM_URL.")
            return

        logger.info("Pipeline starting (one-shot mode): %s", initial)
        result = await self.add_source(initial)
        if not result.get("started") and not result.get("ok"):
            logger.error("Failed to add initial source: %s", result.get("reason"))
            return

        # Wait for that source's ingest task to finish (VOD complete / EOF /
        # cancel) OR the configured timeout.
        entry = self._sources.get(initial)
        try:
            if entry is not None:
                _, task = entry
                await asyncio.wait_for(task, timeout=self._settings.pipeline_timeout_s)
        except TimeoutError:
            logger.info("Pipeline timeout reached (%ds).", self._settings.pipeline_timeout_s)
        except asyncio.CancelledError:
            logger.info("Pipeline cancelled.")
        finally:
            await self._drain_and_stop()

    async def _ingest_from_source(self, url: str, source: AudioSource) -> None:
        """Per-source ingest loop: stream chunks into the shared queue.

        Does NOT send a None sentinel on end — the queue is shared, so one
        source ending must not shut down the workers. Sentinels are only
        emitted by _drain_and_stop() on full pipeline shutdown.
        """
        try:
            async for chunk in source.chunks():
                if not self._running:
                    break
                tmp_dir = str(Path(chunk.audio_path).parent)
                if tmp_dir not in self._tmp_dirs:
                    self._tmp_dirs.append(tmp_dir)
                await self._audio_q.put(chunk)
        except asyncio.CancelledError:
            # Normal path when remove_source() cancels us
            raise
        except Exception:
            logger.exception("Ingestion error for %s", url)
        finally:
            # Deregister + close (idempotent if remove_source already did it)
            self._sources.pop(url, None)
            try:
                await source.close()
            except Exception:
                logger.exception("Error closing source %s", url)
            logger.info("Source ended: %s", url)
            # Schedule a delayed segment close for this stream. Without this,
            # any segments opened for this source stay "Active / Analyzing…"
            # forever because the aggregator never sees another chunk to
            # trigger a check or topic shift. The delay (~12s) gives any
            # in-flight chunks time to flow through transcribe → analyze →
            # broadcast before we close; after close they'd start a new
            # (and also never-closing) segment.
            if self._running:
                asyncio.create_task(
                    self._close_stream_segments_delayed(url),
                    name=f"close-segs:{url[:40]}",
                )

    async def _close_stream_segments_delayed(
        self, url: str, delay: float = 12.0,
    ) -> None:
        """Close active segments for a stream after its source ended.

        Runs as a background task: waits for in-flight chunks to drain, then
        calls aggregator.close_stream() and broadcasts the close events. A
        final LLM verdict inside _close_segment fills in summary + direction
        for segments that never reached the 6-chunk check interval.
        """
        await asyncio.sleep(delay)
        if self._aggregator is None:
            return
        # Guard: if the user added the same URL again in the meantime, the
        # source is active once more — leave its segments alone.
        if url in self._sources:
            return
        try:
            events = await self._aggregator.close_stream(url, reason="stream_ended")
        except Exception:
            logger.exception("Delayed segment close failed for %s", url)
            return
        if not events:
            return
        from src.backtest import segment_reality
        for kind, segment in events:
            try:
                await self._broadcaster.publish(PipelineEvent(
                    event_type=f"segment.{kind}",
                    chunk_id=segment.segment_id,
                    stream_id=url,
                    segment=segment,
                ))
                if kind == "close":
                    segment_reality.enqueue(segment)
            except Exception:
                logger.exception("Failed to broadcast stream_ended segment close")
        logger.info("Closed %d segment(s) on stream end: %s", len(events), url)

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
                    # Publish with per-chunk stream_id so the UI can route
                    # the event to the correct stream card.
                    await self._broadcaster.publish(PipelineEvent(
                        event_type="transcript",
                        chunk_id=chunk.chunk_id,
                        stream_id=chunk.source_url,
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
                        stream_id=transcript.source_url or None,
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
        # Fallback stream_id when the transcript carries no source_url (legacy
        # single-source CLI path). For dashboard multi-source runs, every
        # chunk/transcript carries its own source_url so this fallback is
        # only hit if something upstream forgets to set it.
        fallback_stream_id = (
            self._settings.input_file or self._settings.stream_url or "pipeline"
        )
        while self._running:
            item = await self._scoring_q.get()
            if item is None:
                break
            transcript, result = item
            # Per-chunk routing: use the transcript's own source_url so each
            # stream card in the UI only receives its own signals + segments.
            stream_id = transcript.source_url or fallback_stream_id
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

                # Segment aggregation: hierarchical super-events — scoped per
                # stream_id so two parallel streams don't cross-pollute segments.
                if self._aggregator is not None:
                    try:
                        from src.backtest import segment_reality
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
                            if kind == "close":
                                segment_reality.enqueue(segment)
                    except Exception:
                        logger.exception("Segment aggregation error for chunk %s",
                                         result.chunk_id)
            except Exception:
                logger.exception("Broadcast error for chunk %s", result.chunk_id)

        # Pipeline ending — close any open segments cleanly. We don't know
        # which stream_id they belong to here, so we publish with the
        # segment's own stream_id (set by the aggregator at open time).
        if self._aggregator is not None:
            try:
                from src.backtest import segment_reality
                closing = await self._aggregator.close_all("pipeline_stopped")
                for kind, segment in closing:
                    await self._broadcaster.publish(PipelineEvent(
                        event_type=f"segment.{kind}",
                        chunk_id=segment.segment_id,
                        stream_id=segment.stream_id or fallback_stream_id,
                        segment=segment,
                    ))
                    if kind == "close":
                        segment_reality.enqueue(segment)
            except Exception:
                logger.exception("Error closing segments on shutdown")

        logger.info("Broadcast finished.")

    async def _cleanup(self) -> None:
        """Clean up resources on shutdown (notifier + temp dirs).

        Called from _drain_and_stop() after workers have drained. Does NOT
        touch sources — those are cleaned up inside _drain_and_stop() first.
        """
        if self._notifier:
            try:
                await self._notifier.close()
            except Exception:
                logger.exception("Error closing notifier")
        # Clean up temp directories
        for tmp_dir in self._tmp_dirs:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except OSError:
                pass
        self._tmp_dirs = []
        logger.info("Pipeline stopped and cleaned up.")

    async def _drain_and_stop(self) -> None:
        """Stop all sources, drain the shared workers, then clean up.

        Sequence:
          1. Cancel every active source's ingest task + close its AudioSource
          2. Send None sentinel so _transcribe_loop drains the audio queue
             (which cascades None to transcript_q and scoring_q on its own).
          3. Wait for all worker tasks to exit.
          4. Run _cleanup() for notifier + temp dirs.
        """
        # 1. Cancel sources
        for url, (source, task) in list(self._sources.items()):
            task.cancel()
            try:
                await source.close()
            except Exception:
                logger.exception("Error closing source %s", url)
        self._sources.clear()

        # 2. Signal workers to drain (only if they ever started)
        if self._running:
            try:
                await self._audio_q.put(None)
            except Exception:
                logger.exception("Error sending stop sentinel")

            # 3. Wait for workers to exit
            if self._worker_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*self._worker_tasks, return_exceptions=True),
                        timeout=30.0,
                    )
                except TimeoutError:
                    logger.warning("Workers did not drain in 30s — cancelling.")
                    for t in self._worker_tasks:
                        if not t.done():
                            t.cancel()
            self._worker_tasks = []
            self._running = False

        # 4. Final cleanup
        await self._cleanup()

    def stop(self) -> None:
        """Signal the pipeline to stop all sources and drain workers.

        Safe to call whether the pipeline is running or idle. Schedules the
        actual async teardown as a background task so the caller (often the
        dashboard HTTP handler) doesn't block.
        """
        self._running = False
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()
        else:
            # Dashboard path: no run_task; schedule a drain so everything
            # (source tasks + workers) shuts down cleanly.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(self._drain_and_stop(), name="pipeline-drain")

    async def wait_stopped(self, timeout: float = 10.0) -> bool:
        """Wait for stop() to complete. Returns True on clean exit.

        Covers both paths: run_task (legacy CLI) and drain (dashboard).
        """
        if self._run_task is not None and not self._run_task.done():
            try:
                await asyncio.wait_for(self._run_task, timeout=timeout)
                return True
            except (TimeoutError, asyncio.CancelledError):
                return False
        # Dashboard path: poll _running + _sources
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if not self._running and not self._sources:
                return True
            await asyncio.sleep(0.1)
        return False

    def is_running(self) -> bool:
        return self._running or bool(self._sources)

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

    async def set_runtime_settings(
        self,
        chunk_duration_s: int | None = None,
        whisper_model: str | None = None,
        whisper_language: str | None = None,
    ) -> dict[str, object]:
        """Live-update pipeline settings without a restart.

        Applies:
          - chunk_duration_s → persisted to _settings; applies to NEXT stream start
            (the active source already pre-computed chunk_bytes, changing it
            mid-stream would desync the ffmpeg read loop).
          - whisper_language → swapped immediately on the active Transcriber
            (no model reload — language is a per-call kwarg).
          - whisper_model     → if model string changed and pipeline is running,
            loads a new WhisperModel in an executor (blocking, can take several
            seconds for larger models) and atomically swaps self._transcriber.
            Old in-flight transcriptions finish on the old model (safe).

        Returns {applied: [...], pending: [...], notes: str} so the UI can
        surface what's active vs queued for the next run.
        """
        applied: list[str] = []
        pending: list[str] = []
        notes: list[str] = []

        # 1. Chunk duration — settings-only (next source)
        if chunk_duration_s is not None:
            chunk_duration_s = int(chunk_duration_s)
            if 1 <= chunk_duration_s <= 60:
                if chunk_duration_s != self._settings.chunk_duration_s:
                    self._settings.chunk_duration_s = chunk_duration_s
                    if self._source is not None:
                        pending.append("chunk_duration_s")
                        notes.append(
                            f"Chunk duration {chunk_duration_s}s applies to the "
                            "next stream start (current source keeps its size)."
                        )
                    else:
                        applied.append("chunk_duration_s")
                else:
                    applied.append("chunk_duration_s")

        # 2. Language — swap on active Transcriber immediately
        if whisper_language is not None:
            # "" → auto-detect (None internally); "en" / "cs" / ... → force
            normalized = whisper_language.strip() or None
            self._settings.whisper_language = normalized or ""
            if self._transcriber is not None:
                # Direct attribute swap is safe: Python attribute assign is atomic
                # under the GIL, and faster-whisper reads self._language per-call.
                self._transcriber._language = normalized
            applied.append("whisper_language")

        # 3. Model — reload the WhisperModel if changed AND running
        if whisper_model is not None:
            whisper_model = whisper_model.strip()
            if whisper_model and whisper_model != self._settings.whisper_model_size:
                old_model = self._settings.whisper_model_size
                self._settings.whisper_model_size = whisper_model
                if self._transcriber is not None:
                    try:
                        logger.info(
                            "Hot-swapping Whisper model: %s -> %s (this may take a few seconds)...",
                            old_model, whisper_model,
                        )
                        loop = asyncio.get_running_loop()
                        new_transcriber = await loop.run_in_executor(
                            None,
                            lambda: Transcriber(
                                model_size=whisper_model,
                                device=self._settings.whisper_device,
                                compute_type=self._settings.whisper_compute_type,
                                language=self._settings.whisper_language or None,
                            ),
                        )
                        # Swap — old Transcriber's in-flight calls are unaffected
                        self._transcriber = new_transcriber
                        applied.append("whisper_model")
                        logger.info("Whisper model hot-swap complete (%s).", whisper_model)
                    except Exception as exc:
                        # Revert settings so the pending state matches reality
                        self._settings.whisper_model_size = old_model
                        logger.exception("Whisper model hot-swap failed")
                        notes.append(f"Model reload failed: {exc!s}")
                else:
                    applied.append("whisper_model")
            elif whisper_model == self._settings.whisper_model_size:
                applied.append("whisper_model")

        return {
            "ok": True,
            "applied": sorted(set(applied)),
            "pending": sorted(set(pending)),
            "notes": notes,
            "active": {
                "chunk_duration_s": self._settings.chunk_duration_s,
                "whisper_model": self._settings.whisper_model_size,
                "whisper_language": self._settings.whisper_language,
            },
        }
