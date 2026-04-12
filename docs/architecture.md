# Architecture Document

## System Overview

The Commodity Sentiment Monitor is a real-time pipeline that processes live audio streams to generate commodity market impact signals. It operates in three distinct processing layers, connected by async queues.

## Architecture

```
                    +-----------------+
                    |  Audio Source    |
                    |  (Stream/File)  |
                    +--------+--------+
                             |
                        AudioChunk
                             |
                    +--------v--------+
                    |   Transcriber   |
                    | (faster-whisper)|
                    +--------+--------+
                             |
                        Transcript
                             |
                    +--------v--------+
                    | Entity Extractor|
                    |  (Claude API)   |
                    +--------+--------+
                             |
                     ExtractionResult
                             |
                    +--------v--------+
                    | Impact Scorer   |
                    |  (Claude API)   |
                    +--------+--------+
                             |
                      ScoringResult
                             |
              +--------------+--------------+
              |                             |
     +--------v--------+          +--------v--------+
     |  Web Dashboard   |          | Terminal Display|
     | (FastAPI + SSE)  |          |    (Rich)       |
     +-----------------+          +-----------------+
```

## Layer Details

### 1. Ingestion Layer

**Purpose**: Convert audio sources into fixed-duration PCM chunks.

**Components**:
- `AudioSource` (ABC): Common interface for all sources
- `FileIngestor`: Reads local files via ffmpeg, segments into chunks
- `StreamIngestor`: Connects to live streams via yt-dlp, pipes through ffmpeg

**Key decisions**:
- 16kHz mono PCM (optimal for Whisper)
- 10-second default chunk duration (balance between latency and context)
- Auto-retry with exponential backoff on stream failures
- WAV files on disk (not in-memory) for Whisper compatibility

### 2. STT Layer

**Purpose**: Transcribe audio to text with word-level timestamps.

**Technology**: faster-whisper (CTranslate2-optimized Whisper)

**Key decisions**:
- `base` model for demo (good speed/quality tradeoff on CPU)
- int8 quantization for CPU deployment
- VAD filter enabled to skip silence
- Runs in `ThreadPoolExecutor` to avoid blocking the event loop
- Target: <3x real-time latency

### 3. Analysis Layer

**Purpose**: Extract commodity entities and score market impact.

**Technology**: Claude Haiku 4.5 via Anthropic API

**Key decisions**:
- Two-stage approach (extraction then scoring) for modularity and debuggability
- Canonical commodity identifiers for consistent output
- JSON structured output for reliable parsing
- Conservative confidence scoring (>0.8 = very clear signal only)

## Data Flow

All data flows through Pydantic models, ensuring type safety at every boundary:

```
AudioChunk -> Transcript -> ExtractionResult -> ScoringResult -> PipelineEvent
```

Each model carries a `chunk_id` for end-to-end traceability.

## Concurrency Model

- Single Python process with `asyncio` event loop
- Three `asyncio.Queue` instances decouple layers
- Each layer runs as a separate `asyncio.Task`
- Whisper runs in `ThreadPoolExecutor` (CPU-bound)
- Claude API calls are natively async
- Queue backpressure prevents memory overflow

## Trade-offs

| Decision | Pros | Cons |
|----------|------|------|
| Local Whisper vs API | Free, no network latency | Requires CPU/GPU, larger Docker image |
| Claude Haiku vs Sonnet | Faster, cheaper | Slightly lower accuracy on ambiguous cases |
| asyncio vs Celery | Simple, no infra | Single-machine only |
| Two-stage LLM vs single | Debuggable, modular | Double API latency per chunk |
| WAV files vs memory | Whisper compatibility | Disk I/O overhead |

## Production Improvements

1. **Scalability**: Replace asyncio queues with Redis Streams or Kafka for multi-worker processing
2. **SLA**: Add health checks, dead letter queue for failed chunks, circuit breaker for API calls
3. **Monitoring**: Prometheus metrics (latency histograms, queue depths, API costs), Grafana dashboards
4. **Security**: API key rotation, encrypted at rest, RBAC for dashboard access
5. **Accuracy**: RAG with historical price data, few-shot examples, fine-tuned extraction model
6. **Cost**: Batch similar chunks, cache repeated entity patterns, use smaller model for simple cases
