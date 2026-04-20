# Commodity Sentiment Monitor

Real-time pipeline that extracts speech from live streams, identifies commodity-relevant entities and events, and scores their probable market impact.

```
[Live Stream / Audio File]
        |
    Ingestion (ffmpeg + yt-dlp)
        |
    Audio Chunks (5-15s WAV)
        |
    STT (faster-whisper)
        |
    Transcript
        |
    Entity Extraction (Claude API)
        |
    Commodities, People, Indicators
        |
    Impact Scoring (Claude API)
        |
    Signals: direction, confidence, rationale
        |
    Dashboard (FastAPI + SSE)
```

## Quick Start

### Windows (one-click)

Double-click **`run.bat`**. On first run it creates a `.venv`, installs dependencies and starts the dashboard. Subsequent runs just launch the app.

### Cross-platform

```bash
git clone <repo-url>
cd FutuGen-commodity-sentiment
pip install -e ".[dev]"
python -m src.main
# Open http://localhost:8000 → click "Start Demo" to see it in action
```

The app starts in **onboarding mode** — no API key required. You paste an Anthropic **or** OpenAI key from the onboarding screen (Settings view lets you switch providers at runtime).

```bash
# Run with local audio file
python -m src.main --input-file audio_samples/sample_01_opec.wav

# Run with live YouTube stream
python -m src.main --stream-url "https://www.youtube.com/watch?v=LIVE_ID"

# Zero-cost mode: keyword-based analyzer, no API key needed
python -m src.main --mock --input-file audio_samples/real/opec_raw.wav
```

### Docker

```bash
docker compose up --build
# Open http://localhost:8000 → click "Start Demo"
```

No `.env` file required — the app starts in onboarding mode.

## Setup

### Prerequisites

- Python 3.11+
- ffmpeg (for audio processing)
- yt-dlp (for live stream ingestion, optional)

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Either* | - | Anthropic API key for Claude Haiku |
| `OPENAI_API_KEY` | Either* | - | OpenAI API key for gpt-4o-mini |
| `INPUT_FILE` | No | - | Path to local audio file (optional — onboarding if absent) |
| `STREAM_URL` | No | - | Live stream URL (YouTube, HLS, RTMP) |
| `WHISPER_MODEL_SIZE` | No | `small` | Whisper model: tiny/base/small/medium/large-v3 |
| `WHISPER_DEVICE` | No | `cpu` | `cpu` or `cuda` |
| `CHUNK_DURATION_S` | No | `10` | Audio chunk duration (5-15 seconds) |
| `DASHBOARD_PORT` | No | `8000` | Web dashboard port |

*Either provider works — choose one at onboarding or in the Settings view. The app also runs fully without a key in demo / transcription-only mode.

## Usage

### Local File Mode (Demo)

```bash
# Generate test audio samples first
python scripts/generate_samples.py

# Run on a sample
INPUT_FILE=audio_samples/sample_01_opec.wav python -m src.main
```

### Live Stream Mode

```bash
STREAM_URL="https://www.youtube.com/watch?v=LIVE_ID" python -m src.main
```

### Demo Mode (No API Key Needed)

Start the app without configuration → onboarding page appears with:
- **"Start Demo"** button — replays 12 real evaluation scenarios as live SSE stream
- **Stream discovery** — curated list of Bloomberg, CNBC, and recorded sources
- **API key setup** — instructions for connecting Anthropic API

Dashboard has four views accessible from the top nav:

**Streams view** — each active stream shows:
- Live transcript (updates as Whisper processes audio)
- Pause / Resume / Remove controls per stream
- Detected signals attached to the stream (last 3 visible, expandable to full list)
- Each signal: commodity, direction (bullish/bearish/neutral), confidence, timeframe, rationale

**Commodities view** — 8 tracked commodities with event history:
- Latest sentiment badge per commodity
- Last 3 events visible, expandable to full timeline
- Events accumulate across all streams

**Evaluation view** — live-rendered backtest report: baselines, 95 % CI, reliability diagram, McNemar comparisons, multi-horizon P&L, signal persistence. Pulled from `/api/backtest/professional`.

**Settings view** — swap LLM provider (Anthropic / OpenAI) and API key at runtime without a restart.

### Transcription-Only Mode

Without `ANTHROPIC_API_KEY`, the pipeline runs transcription only (no entity extraction or scoring).

## Real-World Test Results

Tested on real YouTube audio from Bloomberg, CNBC, and financial analysts:

| Source | Type | Keywords Found | Latency |
|--------|------|---------------|---------|
| Bloomberg OPEC coverage | Real TV broadcast | 7/7 (100%) | 0.22x RT |
| Fed/Gold analysis | Real analyst video | 5/5 (100%) | 0.22x RT |
| TTS: OPEC production cut | Generated | 5/5 (100%) | 0.26x RT |
| TTS: Fed rate hike | Generated | 4/4 (100%) | 0.27x RT |
| TTS: US drought | Generated | 5/5 (100%) | 0.23x RT |
| TTS: Middle East tensions | Generated | 5/5 (100%) | 0.22x RT |

All latencies well under the 3x real-time requirement (actual: 0.18-0.27x).

## Project Structure

```
src/
  main.py              # Entrypoint
  config.py            # Settings (pydantic-settings)
  models.py            # Pydantic data models
  pipeline.py          # Orchestrator (async queues)
  ingestion/           # Audio source layer
    audio_source.py    # ABC
    file_ingestor.py   # Local file source
    stream_ingestor.py # Live stream (yt-dlp + ffmpeg)
  stt/
    transcriber.py     # faster-whisper wrapper
  analysis/
    prompts.py         # LLM prompt templates
    entity_extractor.py # Claude API entity extraction
    impact_scorer.py   # Claude API impact scoring
  dashboard/
    server.py          # FastAPI + SSE
    terminal.py        # Rich terminal display
    static/            # Web UI (HTML/CSS/JS)
  prices/
    yahoo_client.py    # Bonus: yfinance integration
  notifications/
    webhook.py         # Bonus: Slack webhook
tests/                 # pytest test suite
evaluation/            # Offline evaluation framework
```

## Technical Decisions

### Why faster-whisper (not OpenAI Whisper API)
- Free: zero API cost for STT
- Fast: 0.2x real-time on CPU with int8 quantization (15x faster than required)
- Local: no network latency, works offline
- Word-level timestamps included
- Default model: `small` (best quality/speed tradeoff on CPU)

### LLM choice: dual-provider (Claude Haiku 4.5 and OpenAI gpt-4o-mini)
- Both providers implemented; user picks at onboarding or in the Settings view
- Chosen for speed + low cost with adequate quality for entity extraction and sentiment scoring
- Structured output support so malformed JSON from the LLM never crashes the pipeline
- Measured cost (see below) is ~$0.0007 / 10 s chunk on OpenAI, ~2× on Claude

### Why asyncio queues (not Kafka/Redis)
- Appropriate scale for single-machine deployment
- Zero infrastructure overhead
- Natural backpressure handling
- Clean async/await integration

### Pipeline Architecture
Three async layers connected by `asyncio.Queue`:
1. **Ingestion** -> AudioChunk -> Queue 1
2. **Transcription** -> Transcript -> Queue 2
3. **Analysis** (extraction + scoring) -> ScoringResult -> Queue 3 -> Dashboard

## Evaluation

```bash
# Level C professional backtest — walk-forward, calibration, baselines, P&L
python -m evaluation.run_professional_backtest
```

Dataset: **387 curated historical events (2018–2024)** — FOMC meetings, OPEC+ decisions, CPI prints, supply shocks, weather, geopolitics — with multi-horizon Yahoo Finance prices (d0, d1, d3, d7, d14, d30). Walk-forward split (train < 2022, calibration = 2022, test ≥ 2023). Baselines computed: random (28.8 %), always-bullish (47.5 %), keyword (25.9 %) — the LLM must beat always-bullish to add value.

Output written to `evaluation/results/professional_backtest_report.md` and rendered live in the Evaluation dashboard view.

## API Cost (measured on real 10-min Yahoo Finance Live stream)

| Provider | Per 10 s chunk | 10 min live | 1 h live | 24/7 month |
|----------|---------------|-------------|----------|-----------|
| OpenAI gpt-4o-mini | $0.00074 | $0.045 | $0.27 | ~$194 |
| Claude Haiku 4.5 | ~$0.0015 | ~$0.09 | ~$0.55 | ~$395 |

A $10 budget covers ~37 h of active OpenAI streaming (~18 h Claude). A proposed noise gate would cut 60–70 % of chunks (see Technický dokument).

## Tests

```bash
pytest tests/ -v
```

## Bonus Features

- **Historical prices**: Yahoo Finance integration via `yfinance`
- **Slack notifications**: Webhook alerts for signals with confidence > 0.8
- **Docker**: Full stack containerization with `docker-compose.yml`

## AI Assistant Disclosure

This project was developed with assistance from Claude (Anthropic) via Claude Code.

## License

MIT
