"""Walk-forward LLM runner for professional backtest.

For each event in a split, runs the entity extractor + impact scorer on the
event's `news_text`, then records the scorer's top signal (direction + confidence)
for the event's commodity. No hindsight: the prompt receives only the
`news_text` field, which by design contains only information that was
public on `event["date"]`.

Usage:
    python -m evaluation.walk_forward --split test \
        [--input evaluation/historical_events_enriched.json] \
        [--output evaluation/results/predictions_llm_test.json]

If ANTHROPIC_API_KEY is not set (or OPENAI_API_KEY + --provider=openai),
the script exits with a clear message — no silent fallback to mock data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from evaluation.splits import SplitConfig, describe_split, split_events
from src.analysis.entity_extractor import EntityExtractor
from src.analysis.impact_scorer import ImpactScorer
from src.config import Settings
from src.models import Transcript

ROOT = Path(__file__).resolve().parent.parent
INPUT_DEFAULT = ROOT / "evaluation" / "historical_events_enriched.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def build_extractor_scorer(settings: Settings) -> tuple[EntityExtractor, ImpactScorer, str]:
    provider = (settings.llm_provider or "anthropic").strip().lower()
    if provider == "openai":
        if not settings.openai_api_key:
            print("ERROR: OPENAI_API_KEY not set. Set it in .env or export it.", file=sys.stderr)
            sys.exit(1)
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        model_e = settings.openai_model_extraction
        model_s = settings.openai_model_scoring
        return (
            EntityExtractor(client, model_e, provider="openai"),
            ImpactScorer(client, model_s, provider="openai"),
            f"openai:{model_s}",
        )
    if not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Set it in .env or export it.", file=sys.stderr)
        sys.exit(1)
    a_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    a_model_e = settings.anthropic_model_extraction
    a_model_s = settings.anthropic_model_scoring
    return (
        EntityExtractor(a_client, a_model_e, provider="anthropic"),
        ImpactScorer(a_client, a_model_s, provider="anthropic"),
        f"anthropic:{a_model_s}",
    )


async def run_event(
    event: dict,
    extractor: EntityExtractor,
    scorer: ImpactScorer,
) -> dict:
    """Run extract+score on one event, pick the top-confidence signal for the
    event's target commodity (fallback: global top signal, else neutral 0.33)."""
    transcript = Transcript(
        chunk_id=event["event_id"],
        language="en",
        language_probability=1.0,
        segments=[],
        full_text=event["news_text"],
        processing_time_s=0.0,
    )
    extraction = await extractor.extract(transcript)
    scoring = await scorer.score(extraction)

    # Prefer a signal matching the target commodity
    target = event["commodity"]
    candidates = [s for s in scoring.signals if s.commodity == target] or list(scoring.signals)
    if candidates:
        top = max(candidates, key=lambda s: s.confidence)
        direction, confidence = top.direction.value, top.confidence
    else:
        direction, confidence = "neutral", 0.33

    return {
        "event_id": event["event_id"],
        "commodity": target,
        "direction": direction,
        "confidence": confidence,
        "source": "llm",
        "all_signals": [s.model_dump(mode="json") for s in scoring.signals],
        "input_tokens": extraction.input_tokens + scoring.input_tokens,
        "output_tokens": extraction.output_tokens + scoring.output_tokens,
    }


async def run_split(
    events: list[dict],
    extractor: EntityExtractor,
    scorer: ImpactScorer,
    concurrency: int = 3,
) -> list[dict]:
    """Run all events, with small concurrency to keep API rate-limit friendly."""
    sem = asyncio.Semaphore(concurrency)
    results: list[dict | None] = [None] * len(events)

    async def worker(i: int, ev: dict) -> None:
        async with sem:
            try:
                results[i] = await run_event(ev, extractor, scorer)
            except Exception as e:
                logger.exception("LLM failed on %s: %s", ev["event_id"], e)
                results[i] = {
                    "event_id": ev["event_id"],
                    "commodity": ev["commodity"],
                    "direction": "neutral",
                    "confidence": 0.33,
                    "source": "llm_error",
                    "error": str(e),
                    "input_tokens": 0,
                    "output_tokens": 0,
                }

    tasks = [asyncio.create_task(worker(i, ev)) for i, ev in enumerate(events)]
    for i, t in enumerate(tasks):
        await t
        if (i + 1) % 10 == 0:
            logger.info("  processed %d / %d events", i + 1, len(tasks))
    return [r for r in results if r is not None]


async def amain(args: argparse.Namespace) -> None:
    with open(args.input, encoding="utf-8") as f:
        all_events = json.load(f)
    logger.info("Loaded %d events.", len(all_events))

    train, calib, test = split_events(all_events, SplitConfig())
    summary = describe_split(train, calib, test)
    logger.info("Split: %s", json.dumps(summary, ensure_ascii=False))

    if args.split == "train":
        events = train
    elif args.split == "calibration":
        events = calib
    elif args.split == "test":
        events = test
    elif args.split == "all":
        events = all_events
    else:
        raise ValueError(f"Unknown split: {args.split}")

    logger.info("Running LLM on %d %s events...", len(events), args.split)
    settings = Settings()
    extractor, scorer, model_tag = build_extractor_scorer(settings)
    logger.info("Provider/model: %s", model_tag)

    preds = await run_split(events, extractor, scorer, concurrency=args.concurrency)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"model": model_tag, "split": args.split, "predictions": preds}, f, indent=2)
    logger.info("Wrote %d predictions to %s", len(preds), args.output)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(INPUT_DEFAULT))
    p.add_argument("--split", default="test", choices=["train", "calibration", "test", "all"])
    p.add_argument("--output", default=None)
    p.add_argument("--concurrency", type=int, default=3)
    args = p.parse_args()
    if args.output is None:
        args.output = str(ROOT / "evaluation" / "results" / f"predictions_llm_{args.split}.json")
    # Also allow env override
    provider = os.environ.get("LLM_PROVIDER")
    if provider:
        os.environ.setdefault("LLM_PROVIDER", provider)
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
