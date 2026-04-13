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

```bash
# Clone and install
git clone <repo-url>
cd commodity-sentiment-monitor
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY and INPUT_FILE

# Run with local audio file
INPUT_FILE=audio_samples/sample_01_opec.wav python -m src.main

# Open dashboard
# http://localhost:8000
```

### Docker

```bash
cp .env.example .env
# Edit .env
docker compose up --build
```

## Setup

### Prerequisites

- Python 3.11+
- ffmpeg (for audio processing)
- yt-dlp (for live stream ingestion, optional)

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | - | Anthropic API key for Claude |
| `INPUT_FILE` | Yes* | - | Path to local audio file |
| `STREAM_URL` | Yes* | - | Live stream URL (YouTube, HLS, RTMP) |
| `WHISPER_MODEL_SIZE` | No | `base` | Whisper model: tiny/base/small/medium/large-v3 |
| `WHISPER_DEVICE` | No | `cpu` | `cpu` or `cuda` |
| `CHUNK_DURATION_S` | No | `10` | Audio chunk duration (5-15 seconds) |
| `DASHBOARD_PORT` | No | `8000` | Web dashboard port |

*One of `INPUT_FILE` or `STREAM_URL` must be set.

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

### Why Claude Haiku 4.5 (not GPT-4)
- Fast: lowest latency in the Claude family
- Cheap: $1/MTok input, $5/MTok output
- Structured output support for guaranteed valid JSON
- Sufficient quality for entity extraction and sentiment scoring

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
# Generate audio samples
python scripts/generate_samples.py

# Run evaluation
python -m evaluation.run_eval
```

12 test excerpts covering: OPEC decisions, Fed rate changes, weather events, sanctions, PMI data, CPI surprises, inventory reports, geopolitical events, neutral commentary, and mixed signals.

## API Cost Estimate

| Scenario | Chunks | Est. Cost |
|----------|--------|-----------|
| Per chunk (10s) | 1 | $0.0034 |
| 30-min demo | 180 | $0.61 |
| Evaluation (12 excerpts) | 12 | $0.04 |
| Development | ~500 | $1.70 |
| **Total** | | **~$2.35** |

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
