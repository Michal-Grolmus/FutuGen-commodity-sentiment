from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.models import CommoditySignal, PipelineEvent

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
MAX_SUBSCRIBERS = 50


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        response = await call_next(request)  # type: ignore[operator]
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
        self._stats = {"chunks_processed": 0, "total_signals": 0, "total_cost_usd": 0.0}

    async def publish(self, event: PipelineEvent) -> None:
        if event.scoring:
            self._stats["chunks_processed"] += 1
            self._stats["total_signals"] += len(event.scoring.signals)
            # Cost estimate: Haiku 4.5 input $0.80/MTok, output $4.00/MTok
            cost = (
                event.scoring.input_tokens * 0.80 / 1_000_000
                + event.scoring.output_tokens * 4.0 / 1_000_000
            )
            if event.extraction:
                cost += (
                    event.extraction.input_tokens * 0.80 / 1_000_000
                    + event.extraction.output_tokens * 4.0 / 1_000_000
                )
            self._stats["total_cost_usd"] += cost

            for sig in event.scoring.signals:
                self._recent_signals.append(sig)
            self._recent_signals = self._recent_signals[-100:]

        # Fan out to subscribers, drop if queue full
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


# Module-level broadcaster (set by create_app)
_broadcaster: SignalBroadcaster | None = None


def create_app(broadcaster: SignalBroadcaster | None = None) -> FastAPI:
    global _broadcaster  # noqa: PLW0603
    _broadcaster = broadcaster or SignalBroadcaster()

    app = FastAPI(title="Commodity Sentiment Monitor")

    # Security middleware
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_methods=["GET"],
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

    @app.get("/api/events")
    async def event_stream(request: Request) -> EventSourceResponse:
        return EventSourceResponse(_broadcaster.subscribe(request))

    @app.get("/api/signals")
    async def get_recent_signals() -> list[dict[str, object]]:
        return [s.model_dump() for s in _broadcaster.get_recent_signals()]

    @app.get("/api/stats")
    async def get_stats() -> dict[str, object]:
        return _broadcaster.get_stats()

    return app
