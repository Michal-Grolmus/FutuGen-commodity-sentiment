from __future__ import annotations

import argparse
import asyncio
import logging
import os

import uvicorn

from src.config import Settings
from src.dashboard.server import SignalBroadcaster, create_app
from src.pipeline import Pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Commodity Sentiment Monitor — real-time commodity impact analysis from live streams",
    )
    parser.add_argument(
        "--input-file", "-f",
        help="Path to local audio file (WAV/MP3). Overrides INPUT_FILE env var.",
    )
    parser.add_argument(
        "--stream-url", "-s",
        help="Live stream URL (YouTube, HLS, RTMP). Overrides STREAM_URL env var.",
    )
    parser.add_argument(
        "--port", "-p", type=int, default=None,
        help="Dashboard port (default: 8000). Overrides DASHBOARD_PORT env var.",
    )
    parser.add_argument(
        "--whisper-model", "-w", default=None,
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size (default: base). Overrides WHISPER_MODEL_SIZE env var.",
    )
    parser.add_argument(
        "--chunk-duration", "-c", type=int, default=None,
        help="Audio chunk duration in seconds (default: 10). Overrides CHUNK_DURATION_S env var.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    # CLI args override env vars
    if args.input_file:
        os.environ["INPUT_FILE"] = args.input_file
    if args.stream_url:
        os.environ["STREAM_URL"] = args.stream_url
    if args.port is not None:
        os.environ["DASHBOARD_PORT"] = str(args.port)
    if args.whisper_model:
        os.environ["WHISPER_MODEL_SIZE"] = args.whisper_model
    if args.chunk_duration is not None:
        os.environ["CHUNK_DURATION_S"] = str(args.chunk_duration)

    settings = Settings()
    broadcaster = SignalBroadcaster()
    app = create_app(broadcaster)

    config = uvicorn.Config(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    has_source = bool(settings.input_file or settings.stream_url)

    if has_source:
        # Full mode: pipeline + dashboard
        pipeline = Pipeline(settings, broadcaster)
        logger.info("Dashboard: http://%s:%d", settings.dashboard_host, settings.dashboard_port)
        logger.info("Starting pipeline with source: %s", settings.input_file or settings.stream_url)
        await asyncio.gather(pipeline.run(), server.serve())
    else:
        # Dashboard-only mode: onboarding + demo replay
        logger.info("Dashboard: http://%s:%d", settings.dashboard_host, settings.dashboard_port)
        logger.info("No input source — starting in dashboard-only mode (onboarding + demo).")
        logger.info("Use --input-file or --stream-url to start the pipeline.")
        await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
