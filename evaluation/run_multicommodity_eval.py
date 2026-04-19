"""Multi-commodity evaluation on the 11 curated historical YouTube videos.

For each entry in `evaluation/historical_test_set.json`:
  1. Run the full pipeline end-to-end on the downloaded audio file
  2. Collect all emitted signals + closed segments
  3. Compare vs. expected_commodities + expected_directions from the fixture

Reports (per-video + aggregate):
  - Commodity recall:  how many expected commodities were detected?
  - Extra commodities: unexpected commodities the model found (may be valid —
    these videos discuss many commodities beyond those in the title)
  - Direction accuracy: among the intersection of expected ∩ detected,
    how often does the direction match?
  - Signal volume + cost per video

Writes:
  - evaluation/results/multicommodity_report.md  — human-readable report
  - evaluation/results/multicommodity_runs.json  — raw per-video results

Requires ANTHROPIC_API_KEY (or OPENAI_API_KEY + LLM_PROVIDER=openai) set in
.env or environment. ~$0.01–$0.10 per video depending on duration.

Usage:  python -m evaluation.run_multicommodity_eval
                 [--limit 3]     # cap number of videos (for quick smoke test)
                 [--timeout 300] # seconds per video
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from src.analysis.entity_extractor import EntityExtractor
from src.analysis.impact_scorer import ImpactScorer
from src.analysis.segment_aggregator import SegmentAggregator, SegmentAggregatorConfig
from src.config import Settings
from src.ingestion.file_ingestor import FileIngestor
from src.models import CommoditySignal, Segment, Transcript
from src.stt.transcriber import Transcriber

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "evaluation" / "historical_test_set.json"
REPORT_PATH = ROOT / "evaluation" / "results" / "multicommodity_report.md"
RUNS_PATH = ROOT / "evaluation" / "results" / "multicommodity_runs.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("multicommodity_eval")


def build_llm_clients(settings: Settings) -> tuple[EntityExtractor, ImpactScorer, SegmentAggregator]:
    provider = (settings.llm_provider or "anthropic").strip().lower()
    if provider == "openai":
        key = settings.openai_api_key
        if not key:
            sys.exit("OPENAI_API_KEY not set.")
        client: Any = AsyncOpenAI(api_key=key)
        ext_model = settings.openai_model_extraction
        score_model = settings.openai_model_scoring
    else:
        provider = "anthropic"
        key = settings.anthropic_api_key
        if not key:
            sys.exit("ANTHROPIC_API_KEY not set.")
        client = AsyncAnthropic(api_key=key)
        ext_model = settings.anthropic_model_extraction
        score_model = settings.anthropic_model_scoring

    extractor = EntityExtractor(client, ext_model, provider=provider)
    scorer = ImpactScorer(client, score_model, provider=provider)
    aggregator = SegmentAggregator(
        client, provider=provider,
        config=SegmentAggregatorConfig(model=score_model),
    )
    return extractor, scorer, aggregator


async def run_video(
    entry: dict[str, Any],
    transcriber: Transcriber,
    extractor: EntityExtractor,
    scorer: ImpactScorer,
    aggregator: SegmentAggregator,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    """Process one video end-to-end and collect signals + segments."""
    audio_path = ROOT / entry["audio_file"]
    if not audio_path.exists():
        return {"video_id": entry["video_id"], "error": f"missing audio file: {audio_path}"}

    start_ts = datetime.now(UTC)
    all_signals: list[CommoditySignal] = []
    all_segments: list[Segment] = []
    total_ext_tokens = {"in": 0, "out": 0}
    total_score_tokens = {"in": 0, "out": 0}
    chunks_processed = 0
    stream_id = entry["video_id"]

    ingestor = FileIngestor(str(audio_path), chunk_duration_s=10)
    try:
        async def _process():
            nonlocal chunks_processed
            async for audio_chunk in ingestor.chunks():
                chunks_processed += 1
                transcript: Transcript = await transcriber.transcribe(audio_chunk)
                # Clean up temp chunk file
                try:
                    Path(audio_chunk.audio_path).unlink(missing_ok=True)
                except OSError:
                    pass
                if not transcript.full_text.strip():
                    continue
                extraction = await extractor.extract(transcript)
                total_ext_tokens["in"] += extraction.input_tokens
                total_ext_tokens["out"] += extraction.output_tokens
                scoring = await scorer.score(extraction)
                total_score_tokens["in"] += scoring.input_tokens
                total_score_tokens["out"] += scoring.output_tokens
                all_signals.extend(scoring.signals)
                # Feed segment aggregator
                events = await aggregator.process_chunk(
                    stream_id, transcript, list(scoring.signals),
                )
                for kind, seg in events:
                    if kind == "close":
                        all_segments.append(seg)
            # End-of-video: close any still-open segments
            events = await aggregator.close_stream(stream_id, reason="video_end")
            for _kind, seg in events:
                all_segments.append(seg)

        await asyncio.wait_for(_process(), timeout=timeout_s)
    except TimeoutError:
        logger.warning("%s: timeout after %ss", entry["video_id"], timeout_s)
    finally:
        await ingestor.close()

    wall_s = (datetime.now(UTC) - start_ts).total_seconds()

    # Aggregate detected commodities (per-signal)
    detected_counts = Counter(s.commodity for s in all_signals)
    # Dominant direction per commodity = signal with highest confidence
    dominant: dict[str, dict[str, Any]] = {}
    for s in all_signals:
        cur = dominant.get(s.commodity)
        if cur is None or s.confidence > cur["confidence"]:
            dominant[s.commodity] = {"direction": s.direction.value, "confidence": s.confidence}

    # Grade against fixture
    expected_set = set(entry["expected_commodities"])
    detected_set = set(detected_counts.keys())
    expected_directions: dict[str, str] = entry.get("expected_directions", {})

    matched = expected_set & detected_set
    missed = expected_set - detected_set
    extra = detected_set - expected_set

    direction_results: list[dict[str, Any]] = []
    for com in sorted(matched):
        exp_dir = expected_directions.get(com, "neutral")
        got_dir = dominant[com]["direction"]
        direction_results.append({
            "commodity": com,
            "expected": exp_dir,
            "detected": got_dir,
            "match": exp_dir == got_dir,
            "confidence": round(dominant[com]["confidence"], 3),
        })

    # Cost estimate (Anthropic Haiku 4.5 rates: $0.80/MTok input, $4.00/MTok output)
    total_cost = (
        total_ext_tokens["in"] * 0.80 / 1_000_000
        + total_ext_tokens["out"] * 4.0 / 1_000_000
        + total_score_tokens["in"] * 0.80 / 1_000_000
        + total_score_tokens["out"] * 4.0 / 1_000_000
    )

    return {
        "video_id": entry["video_id"],
        "title": entry["title"],
        "url": entry["url"],
        "duration_s": entry.get("duration_s", 0),
        "wall_clock_s": round(wall_s, 1),
        "chunks_processed": chunks_processed,
        "total_signals": len(all_signals),
        "total_segments": len(all_segments),
        "expected_commodities": sorted(expected_set),
        "detected_commodities": sorted(detected_set),
        "matched": sorted(matched),
        "missed": sorted(missed),
        "extra": sorted(extra),
        "commodity_recall": len(matched) / len(expected_set) if expected_set else None,
        "direction_results": direction_results,
        "direction_accuracy": (
            sum(1 for d in direction_results if d["match"]) / len(direction_results)
            if direction_results else None
        ),
        "total_cost_usd": round(total_cost, 4),
    }


def generate_report(results: list[dict[str, Any]]) -> str:
    """Render a Markdown summary."""
    lines = [
        "# Multi-commodity evaluation report",
        "",
        f"*Generated: {datetime.now(UTC).isoformat(timespec='seconds')}*",
        "",
        "## Setup",
        "",
        f"- Fixture: `{FIXTURE_PATH.relative_to(ROOT)}`",
        f"- Videos evaluated: {len(results)}",
        "- Pipeline: file ingestion -> Whisper -> Claude Haiku 4.5 extraction + scoring "
        "-> segment aggregation",
        "- Ground truth: derived from video title keywords (commodity list + direction "
        "hints). Not manually verified, so direction accuracy is a rough estimate.",
        "",
        "## Aggregate metrics",
        "",
    ]
    evaluated = [r for r in results if "error" not in r]
    if evaluated:
        total_recall = [r["commodity_recall"] for r in evaluated if r["commodity_recall"] is not None]
        total_dir = [r["direction_accuracy"] for r in evaluated if r["direction_accuracy"] is not None]
        total_signals = sum(r["total_signals"] for r in evaluated)
        total_segments = sum(r["total_segments"] for r in evaluated)
        total_cost = sum(r["total_cost_usd"] for r in evaluated)
        total_duration = sum(r["duration_s"] for r in evaluated)
        total_wall = sum(r["wall_clock_s"] for r in evaluated)
        avg_recall = sum(total_recall) / len(total_recall) if total_recall else 0.0
        avg_dir = sum(total_dir) / len(total_dir) if total_dir else 0.0
        lines.extend([
            f"- **Mean commodity recall**: {avg_recall:.1%}",
            f"- **Mean direction accuracy** (on matched commodities): {avg_dir:.1%}",
            f"- **Total signals**: {total_signals}",
            f"- **Total segments**: {total_segments}",
            f"- **Total cost**: ${total_cost:.4f}",
            f"- **Total audio duration**: {total_duration:.0f}s ({total_duration/60:.1f} min)",
            f"- **Total wall-clock processing**: {total_wall:.0f}s "
            f"({total_wall/total_duration:.2f}× real-time)" if total_duration > 0 else "",
            "",
        ])

    lines.extend(["## Per-video results", ""])
    for r in results:
        lines.append(f"### {r['video_id']}")
        lines.append(f"- **Title**: {r.get('title', '')}")
        lines.append(f"- **URL**: {r.get('url', '')}")
        if "error" in r:
            lines.append(f"- **Error**: {r['error']}")
            lines.append("")
            continue
        lines.append(f"- **Duration**: {r['duration_s']}s, wall-clock {r['wall_clock_s']}s "
                     f"({r['chunks_processed']} chunks)")
        lines.append(f"- **Expected commodities**: {', '.join(r['expected_commodities']) or '(none)'}")
        lines.append(f"- **Detected commodities**: {', '.join(r['detected_commodities']) or '(none)'}")
        if r["matched"]:
            lines.append(f"- **Matched**: {', '.join(r['matched'])}")
        if r["missed"]:
            lines.append(f"- **Missed** (expected but not detected): {', '.join(r['missed'])}")
        if r["extra"]:
            lines.append(f"- **Extra** (detected but not in expected set): "
                         f"{', '.join(r['extra'])}")
        if r["commodity_recall"] is not None:
            lines.append(f"- **Commodity recall**: {r['commodity_recall']:.1%}")
        if r["direction_accuracy"] is not None:
            lines.append(f"- **Direction accuracy**: {r['direction_accuracy']:.1%}")
        if r["direction_results"]:
            lines.append("- **Direction detail**:")
            for d in r["direction_results"]:
                mark = "[ok]" if d["match"] else "[miss]"
                lines.append(f"  - {mark} {d['commodity']}: expected={d['expected']}, "
                             f"detected={d['detected']} (conf {d['confidence']})")
        lines.append(f"- **Signals**: {r['total_signals']} · **Segments**: {r['total_segments']}"
                     f" · **Cost**: ${r['total_cost_usd']:.4f}")
        lines.append("")

    lines.extend([
        "## Caveats",
        "",
        "- **Ground truth from titles**: the `expected_commodities` and "
        "`expected_directions` are derived from video title keywords. Many videos "
        "discuss additional commodities not in the title — those appear as "
        "*Extra*, which is not necessarily an error.",
        "- **Direction accuracy** uses the highest-confidence signal per commodity "
        "across the whole video. A segment-level breakdown would be more precise "
        "but requires manual per-segment labeling.",
        "- **Whisper STT errors** (misheard commodity names, cut-off words at chunk "
        "boundaries) reduce recall, especially for short commodities like 'corn' "
        "that sound like common words.",
        "",
    ])
    return "\n".join(lines) + "\n"


async def amain(args: argparse.Namespace) -> None:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        fixture = json.load(f)
    if args.limit:
        fixture = fixture[:args.limit]

    settings = Settings()
    transcriber = Transcriber(
        model_size=settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        language=settings.whisper_language or None,
    )
    extractor, scorer, aggregator = build_llm_clients(settings)

    results: list[dict[str, Any]] = []
    for i, entry in enumerate(fixture):
        logger.info("[%d/%d] %s (%.0fs) ...", i + 1, len(fixture),
                    entry["video_id"], entry.get("duration_s", 0))
        res = await run_video(
            entry, transcriber, extractor, scorer, aggregator,
            timeout_s=args.timeout,
        )
        results.append(res)
        logger.info("  -> %d signals, recall=%s",
                    res.get("total_signals", 0),
                    f"{res['commodity_recall']:.1%}" if res.get("commodity_recall") is not None else "N/A")

    RUNS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(generate_report(results), encoding="utf-8")
    logger.info("Report: %s", REPORT_PATH.relative_to(ROOT))
    logger.info("Raw runs: %s", RUNS_PATH.relative_to(ROOT))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None, help="Cap number of videos")
    p.add_argument("--timeout", type=float, default=900.0, help="Per-video timeout (s)")
    args = p.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
