"""Offline evaluation runner.

Usage:
    python -m evaluation.run_eval [--test-set evaluation/test_set.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from anthropic import AsyncAnthropic

from evaluation.backtesting import backtest_signals, format_backtest_report
from evaluation.dataset import compute_metrics, evaluate_prediction, generate_report, load_test_set
from src.analysis.entity_extractor import EntityExtractor
from src.analysis.impact_scorer import ImpactScorer
from src.config import Settings
from src.ingestion.file_ingestor import FileIngestor
from src.models import Transcript
from src.stt.transcriber import Transcriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def run_eval(test_set_path: str) -> None:
    settings = Settings()

    if not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY required for evaluation.")
        sys.exit(1)

    test_set = load_test_set(test_set_path)
    logger.info("Loaded %d test excerpts.", len(test_set))

    # Initialize components
    transcriber = Transcriber(
        model_size=settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    extractor = EntityExtractor(client, settings.anthropic_model_extraction)
    scorer = ImpactScorer(client, settings.anthropic_model_scoring)

    predictions = []
    total_cost = 0.0

    for gt in test_set:
        logger.info("Processing: %s — %s", gt.excerpt_id, gt.description)

        audio_path = Path(gt.audio_file)
        if not audio_path.exists():
            logger.warning("Audio file not found: %s — using transcript text directly.", gt.audio_file)
            # Create a synthetic transcript from the ground truth text
            transcript = Transcript(
                chunk_id=gt.excerpt_id,
                language="en",
                language_probability=1.0,
                segments=[],
                full_text=gt.transcript_text,
                processing_time_s=0.0,
            )
        else:
            # Transcribe the actual audio file
            ingestor = FileIngestor(str(audio_path), chunk_duration_s=30)
            async for chunk in ingestor.chunks():
                transcript = await transcriber.transcribe(chunk)
                break  # Just need first chunk
            await ingestor.close()

        # Extract and score
        extraction = await extractor.extract(transcript)
        scoring = await scorer.score(extraction)

        # Track cost
        cost = (
            (extraction.input_tokens + scoring.input_tokens) * 1.0 / 1_000_000
            + (extraction.output_tokens + scoring.output_tokens) * 5.0 / 1_000_000
        )
        total_cost += cost

        pred = evaluate_prediction(scoring.signals, gt)
        predictions.append(pred)

        status = "CORRECT" if pred.direction_correct else "WRONG"
        logger.info(
            "  [%s] Direction: expected=%s, predicted=%s | Commodity recall: %.0f%%",
            status,
            gt.expected_direction.value,
            max(scoring.signals, key=lambda s: s.confidence).direction.value if scoring.signals else "neutral",
            pred.commodity_recall * 100,
        )

    # Compute metrics
    metrics = compute_metrics(predictions)
    metrics["total_api_cost_usd"] = total_cost

    logger.info("=== RESULTS ===")
    logger.info("Direction accuracy: %.1f%%", metrics["direction_accuracy"] * 100)
    logger.info("Avg commodity recall: %.1f%%", metrics["avg_commodity_recall"] * 100)
    logger.info("Total API cost: $%.4f", total_cost)

    # Backtesting: compare signals against historical price movements
    all_signals = [sig for p in predictions for sig in p.predicted_signals]
    if all_signals:
        backtest_results = backtest_signals(all_signals)
        if backtest_results:
            backtest_md = format_backtest_report(backtest_results)
            logger.info("Backtesting: %d signals tested", len(backtest_results))
        else:
            backtest_md = "\n## Backtesting Results\n\nNo price data available for backtesting.\n"
    else:
        backtest_md = ""

    # Save results
    report_path = "evaluation/results/evaluation_report.md"
    generate_report(metrics, report_path)
    # Append backtesting results to report
    if backtest_md:
        with open(report_path, "a", encoding="utf-8") as f:
            f.write("\n" + backtest_md)
    logger.info("Report saved: %s", report_path)

    # Save raw predictions
    raw_path = "evaluation/results/predictions.json"
    Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump([p.model_dump(mode="json") for p in predictions], f, indent=2)
    logger.info("Raw predictions saved: %s", raw_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run offline evaluation")
    parser.add_argument("--test-set", default="evaluation/test_set.json")
    args = parser.parse_args()
    asyncio.run(run_eval(args.test_set))


if __name__ == "__main__":
    main()
