from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.models import CommoditySignal, PipelineEvent

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
PROJECT_ROOT = Path(__file__).parent.parent.parent
MAX_SUBSCRIBERS = 50

CURATED_STREAMS = [
    {
        "name": "Bloomberg Business News Live",
        "url": "https://www.youtube.com/watch?v=iEpJwprxDdk",
        "description": "Bloomberg 24/7 live market coverage",
        "type": "live",
    },
    {
        "name": "Bloomberg Originals",
        "url": "https://www.youtube.com/watch?v=DxmDPrfinXY",
        "description": "News, documentaries & more",
        "type": "live",
    },
    {
        "name": "Yahoo Finance Live",
        "url": "https://www.youtube.com/watch?v=KQp-e_XQnDE",
        "description": "Yahoo Finance 24/7 daily market coverage",
        "type": "live",
    },
    {
        "name": "CNBC Marathon",
        "url": "https://www.youtube.com/watch?v=9NyxcX3rhQs",
        "description": "CNBC Marathon 24/7 — documentaries and deep dives",
        "type": "live",
    },
    {
        "name": "OPEC Production Cut (recorded)",
        "url": "audio_samples/real/opec_raw.wav",
        "description": "Bloomberg OPEC+ analysis — oil production cuts 2025",
        "type": "file",
    },
    {
        "name": "Fed & Gold Analysis (recorded)",
        "url": "audio_samples/real/fed_raw.wav",
        "description": "Gold and silver evening report — Fed monetary policy",
        "type": "file",
    },
    {
        "name": "TTS: OPEC Cut Announcement",
        "url": "audio_samples/sample_01_opec.wav",
        "description": "Simulated OPEC production cut — bullish oil signal",
        "type": "file",
    },
    {
        "name": "TTS: Middle East Tensions",
        "url": "audio_samples/sample_09_mideast.wav",
        "description": "Simulated geopolitical escalation — shipping attacks",
        "type": "file",
    },
]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        response = await call_next(request)  # type: ignore[operator]
        assert isinstance(response, Response)  # mypy: narrow type
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Always send no-cache for HTML + JS + CSS — we iterate frequently and
        # a stale cached dashboard silently breaks features (symptoms: Start
        # button does nothing, etc.). This costs nothing in practice because
        # the app is a dev-grade demo.
        path = request.url.path
        if path == "/" or path.endswith((".html", ".js", ".css", ".json")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


class SignalBroadcaster:
    """Fan-out: accepts events from pipeline, distributes to all SSE clients."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[PipelineEvent]] = []
        self._recent_signals: list[CommoditySignal] = []
        self._stats: dict[str, object] = {
            "chunks_processed": 0,
            "total_signals": 0,
            "total_cost_usd": 0.0,
            "avg_stt_latency_ms": 0.0,
            "avg_extraction_latency_ms": 0.0,
            "avg_scoring_latency_ms": 0.0,
        }
        self._stt_latencies: list[float] = []
        self._extraction_latencies: list[float] = []
        self._scoring_latencies: list[float] = []
        # Heatmap: last confidence per commodity
        self._heatmap: dict[str, dict[str, object]] = {}
        # Active + closed segments (last 50) for late SSE subscribers
        self._active_segments: dict[str, dict[str, object]] = {}  # segment_id -> dict
        self._recent_segments: list[dict[str, object]] = []

    async def publish(self, event: PipelineEvent) -> None:
        # Track latencies
        if event.transcript:
            self._stt_latencies.append(event.transcript.processing_time_s * 1000)
            self._stt_latencies = self._stt_latencies[-50:]
            self._stats["avg_stt_latency_ms"] = (
                sum(self._stt_latencies) / len(self._stt_latencies)
            )

        if event.extraction:
            self._extraction_latencies.append(event.extraction.processing_time_s * 1000)
            self._extraction_latencies = self._extraction_latencies[-50:]
            self._stats["avg_extraction_latency_ms"] = (
                sum(self._extraction_latencies) / len(self._extraction_latencies)
            )

        if event.scoring:
            self._scoring_latencies.append(event.scoring.processing_time_s * 1000)
            self._scoring_latencies = self._scoring_latencies[-50:]
            self._stats["avg_scoring_latency_ms"] = (
                sum(self._scoring_latencies) / len(self._scoring_latencies)
            )
            self._stats["chunks_processed"] = int(str(self._stats["chunks_processed"])) + 1
            self._stats["total_signals"] = int(str(self._stats["total_signals"])) + len(
                event.scoring.signals
            )
            # Cost: Haiku 4.5 input $0.80/MTok, output $4.00/MTok
            cost = (
                event.scoring.input_tokens * 0.80 / 1_000_000
                + event.scoring.output_tokens * 4.0 / 1_000_000
            )
            if event.extraction:
                cost += (
                    event.extraction.input_tokens * 0.80 / 1_000_000
                    + event.extraction.output_tokens * 4.0 / 1_000_000
                )
            self._stats["total_cost_usd"] = float(str(self._stats["total_cost_usd"])) + cost

            for sig in event.scoring.signals:
                self._recent_signals.append(sig)
                self._heatmap[sig.commodity] = {
                    "display_name": sig.display_name,
                    "direction": sig.direction.value,
                    "confidence": sig.confidence,
                }
            self._recent_signals = self._recent_signals[-100:]

        # Segment events: track active + recent (closed) segments
        if event.segment and event.event_type.startswith("segment."):
            seg_dict = event.segment.model_dump(mode="json")
            seg_id = event.segment.segment_id
            if event.event_type == "segment.open":
                self._active_segments[seg_id] = seg_dict
            elif event.event_type == "segment.update":
                self._active_segments[seg_id] = seg_dict
            elif event.event_type == "segment.close":
                self._active_segments.pop(seg_id, None)
                self._recent_segments.append(seg_dict)
                self._recent_segments = self._recent_segments[-50:]

        # Fan out to subscribers
        dead: list[asyncio.Queue[PipelineEvent]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    async def subscribe(self, request: Request) -> AsyncGenerator[dict[str, str], None]:
        if len(self._subscribers) >= MAX_SUBSCRIBERS:
            yield {"event": "error", "data": '{"error":"too many connections"}'}
            return

        q: asyncio.Queue[PipelineEvent] = asyncio.Queue(maxsize=50)
        self._subscribers.append(q)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield {"event": event.event_type, "data": event.model_dump_json()}
                except TimeoutError:
                    yield {"event": "keepalive", "data": "{}"}
        finally:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def get_recent_signals(self) -> list[CommoditySignal]:
        return list(self._recent_signals)

    def get_stats(self) -> dict[str, object]:
        return dict(self._stats)

    def get_heatmap(self) -> dict[str, dict[str, object]]:
        return dict(self._heatmap)

    def get_active_segments(self) -> list[dict[str, object]]:
        return list(self._active_segments.values())

    def get_recent_segments(self) -> list[dict[str, object]]:
        return list(self._recent_segments)


_broadcaster: SignalBroadcaster | None = None
_pipeline_ref: object | None = None  # weak reference to running Pipeline; set by create_app


def set_pipeline(pipeline: object) -> None:
    """Inject pipeline instance so API endpoints can update it at runtime."""
    global _pipeline_ref  # noqa: PLW0603
    _pipeline_ref = pipeline


def create_app(broadcaster: SignalBroadcaster | None = None) -> FastAPI:
    global _broadcaster  # noqa: PLW0603
    _broadcaster = broadcaster or SignalBroadcaster()

    app = FastAPI(title="Commodity Sentiment Monitor")

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html_path = STATIC_DIR / "index.html"
        html = html_path.read_text(encoding="utf-8")
        # Cache-bust: append mtime of app.js / style.css to <script> / <link> refs.
        # Browsers treat /static/app.js?v=123 and /static/app.js?v=456 as
        # different resources → forced fresh fetch on every server restart.
        try:
            js_v = int((STATIC_DIR / "app.js").stat().st_mtime)
            css_v = int((STATIC_DIR / "style.css").stat().st_mtime)
            html = html.replace("/static/app.js", f"/static/app.js?v={js_v}")
            html = html.replace("/static/style.css", f"/static/style.css?v={css_v}")
        except OSError:
            pass  # If stat fails, serve without cache-bust — no-cache headers still apply
        return HTMLResponse(content=html)

    @app.get("/api/config")
    async def get_config() -> dict[str, object]:
        """Return current configuration state for onboarding UI."""
        env_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
        env_openai = bool(os.environ.get("OPENAI_API_KEY", ""))
        runtime_anthropic = False
        runtime_openai = False
        provider = "anthropic"
        # Prefer live settings over env (settings can be mutated at runtime
        # via /api/settings/pipeline without restarting).
        whisper_model = os.environ.get("WHISPER_MODEL_SIZE", "small")
        whisper_language = os.environ.get("WHISPER_LANGUAGE", "en")
        chunk_duration_s = int(os.environ.get("CHUNK_DURATION_S", "10") or 10)
        if _pipeline_ref is not None:
            settings = getattr(_pipeline_ref, "_settings", None)
            if settings is not None:
                runtime_anthropic = bool(getattr(settings, "anthropic_api_key", ""))
                runtime_openai = bool(getattr(settings, "openai_api_key", ""))
                provider = getattr(settings, "llm_provider", "anthropic") or "anthropic"
                whisper_model = getattr(settings, "whisper_model_size", whisper_model)
                whisper_language = getattr(settings, "whisper_language", whisper_language)
                chunk_duration_s = getattr(settings, "chunk_duration_s", chunk_duration_s)
        mock = os.environ.get("USE_MOCK_ANALYZER", "").lower() == "true"
        has_key = env_anthropic or env_openai or runtime_anthropic or runtime_openai or mock
        return {
            "has_api_key": has_key,
            "mock_mode": mock,
            "llm_provider": provider,
            "anthropic_active": env_anthropic or runtime_anthropic,
            "openai_active": env_openai or runtime_openai,
            "whisper_model": whisper_model,
            "whisper_language": whisper_language,
            "chunk_duration_s": chunk_duration_s,
            "price_tracking": os.environ.get("ENABLE_PRICE_TRACKING", "true"),
            "input_source": os.environ.get("INPUT_FILE", "") or os.environ.get("STREAM_URL", ""),
        }

    @app.post("/api/pipeline/start")
    async def pipeline_start(payload: dict[str, object]) -> dict[str, object]:
        """Add a source to the pipeline (multi-source supported).

        Called from the dashboard's "Add Stream" / Saved Streams flow. Adding
        the same URL twice is a no-op (returns reason="already active").
        """
        source = str(payload.get("source", "")).strip()
        if not source:
            return {"ok": False, "error": "source is required"}
        if _pipeline_ref is None:
            return {"ok": False, "error": "Pipeline not initialized"}
        # Prefer async add_source() when available (new multi-source API).
        # Fall back to the sync shim for any older subclass/mock.
        if hasattr(_pipeline_ref, "add_source"):
            return await _pipeline_ref.add_source(source)
        if hasattr(_pipeline_ref, "start_with_source"):
            return _pipeline_ref.start_with_source(source)
        return {"ok": False, "error": "Pipeline doesn't support runtime start"}

    @app.post("/api/pipeline/stop")
    async def pipeline_stop(payload: dict[str, object] | None = None) -> dict[str, object]:
        """Stop sources.

        - With payload {"source": URL}: stop that specific stream, leave
          the rest running. Used by the per-card Remove button.
        - Without payload (or empty): stop ALL sources and drain workers.
          Used for hard reset / shutdown.
        """
        if _pipeline_ref is None:
            return {"ok": False, "error": "Pipeline not initialized"}
        source = ""
        if payload is not None:
            source = str(payload.get("source", "")).strip()

        if source and hasattr(_pipeline_ref, "remove_source"):
            # Per-stream stop — other sources keep running
            result = await _pipeline_ref.remove_source(source)
            return {
                "ok": bool(result.get("ok")),
                "scope": "source",
                "source": source,
                "was_running": bool(result.get("ok")),
                "stopped_cleanly": True,
                **({"reason": result["reason"]} if "reason" in result else {}),
            }

        # Full stop
        if not hasattr(_pipeline_ref, "stop"):
            return {"ok": False, "error": "Pipeline doesn't support stop"}
        was_running = bool(getattr(_pipeline_ref, "_running", False)) or bool(
            getattr(_pipeline_ref, "_sources", {})
        )
        _pipeline_ref.stop()
        stopped_cleanly = True
        if hasattr(_pipeline_ref, "wait_stopped"):
            stopped_cleanly = await _pipeline_ref.wait_stopped(timeout=5.0)
        return {
            "ok": True,
            "scope": "all",
            "was_running": was_running,
            "stopped_cleanly": stopped_cleanly,
        }

    @app.get("/api/pipeline/status")
    async def pipeline_status() -> dict[str, object]:
        """Report active source list + worker state."""
        if _pipeline_ref is None:
            return {"running": False, "sources": [], "reason": "no pipeline"}
        running = bool(getattr(_pipeline_ref, "_running", False))
        sources: list[str] = []
        if hasattr(_pipeline_ref, "active_sources"):
            sources = list(_pipeline_ref.active_sources())
        else:
            # Fallback for legacy mocks: derive from settings
            settings = getattr(_pipeline_ref, "_settings", None)
            if settings is not None:
                s = settings.input_file or settings.stream_url or None
                if s:
                    sources = [s]
        return {
            "running": running or bool(sources),
            "sources": sources,
            # Legacy scalar for older UI code (first active source)
            "source": sources[0] if sources else None,
        }

    @app.post("/api/settings/api-key")
    async def set_api_key(payload: dict[str, object]) -> dict[str, object]:
        """Live-update the LLM API key (optionally switching provider)."""
        key = str(payload.get("api_key", "")).strip()
        provider_raw = payload.get("provider")
        provider = str(provider_raw).strip().lower() if provider_raw else None
        if provider and provider not in ("anthropic", "openai"):
            return {"error": f"Unknown provider '{provider}'. Use 'anthropic' or 'openai'."}
        if _pipeline_ref is None:
            return {"error": "Pipeline not available (dashboard-only mode)."}
        if not hasattr(_pipeline_ref, "set_api_key"):
            return {"error": "Pipeline doesn't support live key updates."}
        active = _pipeline_ref.set_api_key(key, provider)
        settings = getattr(_pipeline_ref, "_settings", None)
        active_provider = getattr(settings, "llm_provider", "anthropic") if settings else "anthropic"
        return {"ok": True, "active": active, "provider": active_provider}

    @app.post("/api/settings/pipeline")
    async def set_pipeline_settings(payload: dict[str, object]) -> dict[str, object]:
        """Live-update chunk duration, Whisper model, and transcript language.

        No restart needed:
          * language swaps instantly on the active Transcriber.
          * model triggers an in-executor WhisperModel reload if running.
          * chunk duration is persisted; applies to the next stream start.
        """
        if _pipeline_ref is None:
            return {"ok": False, "error": "Pipeline not available."}
        if not hasattr(_pipeline_ref, "set_runtime_settings"):
            return {"ok": False, "error": "Pipeline doesn't support live settings."}

        # Parse + validate chunk (5-15 per assignment spec)
        chunk_raw = payload.get("chunk_duration_s")
        chunk: int | None = None
        if chunk_raw is not None and str(chunk_raw).strip() != "":
            try:
                chunk = int(chunk_raw)
            except (TypeError, ValueError):
                return {"ok": False, "error": "chunk_duration_s must be an integer."}
            if not 5 <= chunk <= 15:
                return {"ok": False, "error": "chunk_duration_s must be 5-15."}

        # Parse + validate whisper model (must be one of the known sizes)
        model_raw = payload.get("whisper_model")
        model: str | None = None
        if model_raw is not None and str(model_raw).strip() != "":
            model = str(model_raw).strip()
            allowed = {"tiny", "base", "small", "medium", "large-v3"}
            if model not in allowed:
                return {
                    "ok": False,
                    "error": f"whisper_model must be one of {sorted(allowed)}.",
                }

        # Parse language: empty string = auto-detect (allowed)
        lang_raw = payload.get("whisper_language")
        lang: str | None = str(lang_raw).strip() if lang_raw is not None else None

        try:
            result = await _pipeline_ref.set_runtime_settings(
                chunk_duration_s=chunk,
                whisper_model=model,
                whisper_language=lang,
            )
        except Exception as exc:  # noqa: BLE001 — surface any error to the client
            logger.exception("set_runtime_settings failed")
            return {"ok": False, "error": f"Apply failed: {exc!s}"}
        return result

    @app.get("/api/events")
    async def event_stream(request: Request) -> EventSourceResponse:
        return EventSourceResponse(_broadcaster.subscribe(request))

    @app.get("/api/signals")
    async def get_recent_signals() -> list[dict[str, object]]:
        return [s.model_dump() for s in _broadcaster.get_recent_signals()]

    @app.get("/api/stats")
    async def get_stats() -> dict[str, object]:
        return _broadcaster.get_stats()

    @app.get("/api/heatmap")
    async def get_heatmap() -> dict[str, dict[str, object]]:
        return _broadcaster.get_heatmap()

    @app.get("/api/backtest/stats")
    async def backtest_stats() -> dict[str, object]:
        """Aggregate backtest accuracy from signal log, grouped by timeframe."""
        from src.backtest import signal_log
        return signal_log.compute_stats()

    @app.get("/api/backtest/log")
    async def backtest_log(limit: int = 50) -> list[dict[str, object]]:
        """Recent signal log entries (with backtest results if available)."""
        from src.backtest import signal_log
        entries = signal_log.read_all()
        return entries[-limit:]

    @app.get("/api/segments/active")
    async def segments_active() -> list[dict[str, object]]:
        """Currently open segments for all streams (for dashboard hydration)."""
        return _broadcaster.get_active_segments()

    @app.get("/api/segments/recent")
    async def segments_recent(limit: int = 50) -> list[dict[str, object]]:
        """Recently closed segments — shown as history on commodity view."""
        entries = _broadcaster.get_recent_segments()
        return entries[-limit:]

    @app.get("/api/segments/log")
    async def segments_log(limit: int = 100) -> list[dict[str, object]]:
        """Full segment log from disk (closed segments, newest last)."""
        from src.backtest import segment_log as seg_log
        entries = seg_log.read_all()
        return entries[-limit:]

    @app.get("/api/segments/stats")
    async def segments_stats() -> dict[str, object]:
        """Per-commodity and per-stream segment accuracy (once reality_score exists)."""
        from src.backtest import segment_log as seg_log
        return seg_log.compute_stats()

    @app.get("/api/backtest/professional")
    async def backtest_professional() -> dict[str, object]:
        """Return the professional backtest summary (dataset, baselines, LLM, P&L)."""
        summary_path = PROJECT_ROOT / "evaluation" / "results" / "professional_summary.json"
        if not summary_path.exists():
            return {"error": "Not generated yet. Run `python -m evaluation.run_professional_backtest`."}
        with open(summary_path, encoding="utf-8") as f:
            return json.load(f)

    @app.get("/api/backtest/reliability.svg")
    async def backtest_reliability_svg(split: str = "test") -> Response:
        """Return the reliability diagram SVG for the requested split."""
        fname = "reliability_llm_test.svg" if split == "test" else "reliability_llm_calibration.svg"
        svg_path = PROJECT_ROOT / "evaluation" / "results" / fname
        if not svg_path.exists():
            return Response(
                content='<svg xmlns="http://www.w3.org/2000/svg" width="480" height="380">'
                        '<rect width="480" height="380" fill="#0d1117"/>'
                        '<text x="240" y="190" fill="#8b949e" text-anchor="middle" '
                        'font-family="system-ui" font-size="14">Run walk-forward + backtest to generate</text>'
                        '</svg>',
                media_type="image/svg+xml",
            )
        return Response(content=svg_path.read_text(encoding="utf-8"), media_type="image/svg+xml")

    @app.get("/api/backtest/report")
    async def backtest_report() -> Response:
        """Return the rendered Markdown report as plain text."""
        report_path = PROJECT_ROOT / "evaluation" / "results" / "professional_backtest_report.md"
        if not report_path.exists():
            return Response(content="Report not generated yet.", media_type="text/plain")
        return Response(content=report_path.read_text(encoding="utf-8"), media_type="text/markdown")

    @app.get("/api/streams")
    async def get_streams() -> list[dict[str, str]]:
        """Return curated list of commodity news streams."""
        return CURATED_STREAMS

    @app.get("/api/commodities")
    async def list_commodities() -> list[dict[str, object]]:
        from src.analysis import commodity_registry
        return [
            {"name": c.name, "display_name": c.display_name,
             "keywords": c.keywords, "yahoo_ticker": c.yahoo_ticker}
            for c in commodity_registry.all_commodities()
        ]

    @app.post("/api/commodities")
    async def add_commodity(payload: dict[str, object]) -> dict[str, object]:
        from src.analysis import commodity_registry
        name = str(payload.get("name", "")).strip().lower().replace(" ", "_")
        display = str(payload.get("display_name", "")).strip()
        keywords_raw = payload.get("keywords", [])
        if isinstance(keywords_raw, str):
            keywords = [k.strip().lower() for k in keywords_raw.split(",") if k.strip()]
        else:
            keywords = [str(k).strip().lower() for k in keywords_raw if str(k).strip()]
        ticker = str(payload.get("yahoo_ticker", "")).strip()
        if not name or not display:
            return {"error": "name and display_name required"}
        try:
            c = commodity_registry.add(name, display, keywords, ticker)
        except ValueError as e:
            return {"error": str(e)}
        return {"ok": True, "name": c.name, "display_name": c.display_name}

    @app.delete("/api/commodities/{name}")
    async def remove_commodity(name: str) -> dict[str, object]:
        from src.analysis import commodity_registry
        if commodity_registry.remove(name):
            return {"ok": True}
        return {"error": f"Commodity '{name}' not found"}

    @app.get("/api/prices/{commodity}")
    async def get_commodity_prices(commodity: str) -> dict[str, object]:
        """Get 30-day price history for a commodity (for sparkline charts)."""
        from src.prices.yahoo_client import COMMODITY_TICKERS, PriceClient

        if commodity not in COMMODITY_TICKERS:
            return {"error": f"Unknown commodity: {commodity}", "data": []}
        client = PriceClient()
        history = client.get_history(commodity, period="1mo")
        current = client.get_current_price(commodity)
        change = client.get_price_change_24h(commodity)
        return {
            "commodity": commodity,
            "current_price": current,
            "change_24h": change,
            "history": history,
        }

    @app.get("/api/prices")
    async def get_all_prices() -> dict[str, dict[str, object]]:
        """Get current prices for all tracked commodities."""
        from src.prices.yahoo_client import PriceClient

        client = PriceClient()
        return client.get_all_prices()

    @app.get("/api/demo")
    async def demo_stream(request: Request) -> EventSourceResponse:
        """Stream saved evaluation results as live demo (no API key needed).

        Distributes events across 3 simulated streams to show multi-stream behavior.
        """

        # Assign each excerpt to one of 3 streams (by topic)
        stream_map = {
            "opec_01": "Bloomberg Live",
            "inventory_01": "Bloomberg Live",
            "geopolitical_01": "Bloomberg Live",
            "sanctions_01": "Bloomberg Live",
            "mining_01": "Bloomberg Live",
            "fed_01": "CNBC Markets",
            "fed_02": "CNBC Markets",
            "inflation_01": "CNBC Markets",
            "mixed_01": "CNBC Markets",
            "weather_01": "Yahoo Finance",
            "china_01": "Yahoo Finance",
            "neutral_01": "Yahoo Finance",
        }

        async def generate() -> AsyncGenerator[dict[str, str], None]:
            predictions_path = PROJECT_ROOT / "evaluation" / "results" / "predictions.json"
            if not predictions_path.exists():
                yield {"event": "error", "data": '{"error":"No demo data available"}'}
                return

            with open(predictions_path, encoding="utf-8") as f:
                predictions = json.load(f)

            for pred in predictions:
                if await request.is_disconnected():
                    break

                gt = pred.get("ground_truth", {})
                signals = pred.get("predicted_signals", [])
                eid = pred.get("excerpt_id", "demo")
                stream_id = stream_map.get(eid, "Bloomberg Live")

                text = gt.get("transcript_text", gt.get("description", ""))
                if text:
                    yield {
                        "event": "transcript",
                        "data": json.dumps({
                            "event_type": "transcript", "chunk_id": eid,
                            "stream_id": stream_id,
                            "timestamp": "2025-01-01T00:00:00Z",
                            "transcript": {
                                "chunk_id": eid, "language": "en",
                                "language_probability": 1.0, "segments": [],
                                "full_text": text, "processing_time_s": 0.5,
                            },
                        }),
                    }

                await asyncio.sleep(1.0)

                if signals:
                    yield {
                        "event": "signal",
                        "data": json.dumps({
                            "event_type": "signal", "chunk_id": eid,
                            "stream_id": stream_id,
                            "timestamp": "2025-01-01T00:00:00Z",
                            "scoring": {
                                "chunk_id": eid, "signals": signals,
                                "model_used": "claude-haiku-4-5 (demo)",
                                "input_tokens": 0, "output_tokens": 0,
                                "processing_time_s": 0.8,
                            },
                        }),
                    }

                await asyncio.sleep(2.0)

        return EventSourceResponse(generate())

    return app
