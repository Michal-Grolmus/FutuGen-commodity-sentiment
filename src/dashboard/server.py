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
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

    @app.get("/api/config")
    async def get_config() -> dict[str, object]:
        """Return current configuration state for onboarding UI."""
        env_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
        env_openai = bool(os.environ.get("OPENAI_API_KEY", ""))
        runtime_anthropic = False
        runtime_openai = False
        provider = "anthropic"
        if _pipeline_ref is not None:
            settings = getattr(_pipeline_ref, "_settings", None)
            if settings is not None:
                runtime_anthropic = bool(getattr(settings, "anthropic_api_key", ""))
                runtime_openai = bool(getattr(settings, "openai_api_key", ""))
                provider = getattr(settings, "llm_provider", "anthropic") or "anthropic"
        mock = os.environ.get("USE_MOCK_ANALYZER", "").lower() == "true"
        has_key = env_anthropic or env_openai or runtime_anthropic or runtime_openai or mock
        return {
            "has_api_key": has_key,
            "mock_mode": mock,
            "llm_provider": provider,
            "anthropic_active": env_anthropic or runtime_anthropic,
            "openai_active": env_openai or runtime_openai,
            "whisper_model": os.environ.get("WHISPER_MODEL_SIZE", "small"),
            "price_tracking": os.environ.get("ENABLE_PRICE_TRACKING", "true"),
            "input_source": os.environ.get("INPUT_FILE", "") or os.environ.get("STREAM_URL", ""),
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
