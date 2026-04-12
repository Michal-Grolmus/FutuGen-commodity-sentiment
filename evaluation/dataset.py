from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from src.models import (
    CommoditySignal,
    Direction,
    EvalPrediction,
    GroundTruthLabel,
)


def load_test_set(path: str = "evaluation/test_set.json") -> list[GroundTruthLabel]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [GroundTruthLabel(**item) for item in data]


def evaluate_prediction(
    signals: list[CommoditySignal],
    ground_truth: GroundTruthLabel,
) -> EvalPrediction:
    """Compare predicted signals against ground truth for one excerpt."""
    # Determine predicted direction (highest confidence signal, or neutral if no signals)
    if not signals:
        predicted_direction = Direction.NEUTRAL
    else:
        best_signal = max(signals, key=lambda s: s.confidence)
        predicted_direction = best_signal.direction

    direction_correct = predicted_direction == ground_truth.expected_direction

    # Commodity recall
    if not ground_truth.expected_commodities:
        commodity_recall = 1.0 if not signals else 0.0
    else:
        predicted_commodities = {s.commodity for s in signals}
        hits = sum(1 for c in ground_truth.expected_commodities if c in predicted_commodities)
        commodity_recall = hits / len(ground_truth.expected_commodities)

    return EvalPrediction(
        excerpt_id=ground_truth.excerpt_id,
        predicted_signals=signals,
        ground_truth=ground_truth,
        direction_correct=direction_correct,
        commodity_recall=commodity_recall,
    )


def compute_metrics(predictions: list[EvalPrediction]) -> dict[str, object]:
    """Compute aggregate metrics from evaluation predictions."""
    n = len(predictions)
    if n == 0:
        return {}

    direction_accuracy = sum(1 for p in predictions if p.direction_correct) / n
    avg_commodity_recall = sum(p.commodity_recall for p in predictions) / n

    # Confusion matrix
    labels = [Direction.BULLISH, Direction.BEARISH, Direction.NEUTRAL]
    confusion: dict[str, dict[str, int]] = {l.value: {l2.value: 0 for l2 in labels} for l in labels}

    for pred in predictions:
        actual = pred.ground_truth.expected_direction.value
        if pred.predicted_signals:
            best = max(pred.predicted_signals, key=lambda s: s.confidence)
            predicted = best.direction.value
        else:
            predicted = Direction.NEUTRAL.value
        confusion[actual][predicted] += 1

    # Per-excerpt details
    errors = [
        {
            "excerpt_id": p.excerpt_id,
            "expected": p.ground_truth.expected_direction.value,
            "predicted": (
                max(p.predicted_signals, key=lambda s: s.confidence).direction.value
                if p.predicted_signals
                else "neutral"
            ),
            "description": p.ground_truth.description,
        }
        for p in predictions
        if not p.direction_correct
    ]

    return {
        "total_excerpts": n,
        "direction_accuracy": direction_accuracy,
        "avg_commodity_recall": avg_commodity_recall,
        "confusion_matrix": confusion,
        "errors": errors,
    }


def generate_report(metrics: dict[str, object], output_path: str) -> None:
    """Write evaluation report as markdown."""
    lines = [
        "# Evaluation Report",
        "",
        "## Summary",
        "",
        f"- **Total excerpts**: {metrics['total_excerpts']}",
        f"- **Direction accuracy**: {metrics['direction_accuracy']:.1%}",
        f"- **Avg commodity recall**: {metrics['avg_commodity_recall']:.1%}",
        "",
        "## Confusion Matrix",
        "",
        "| Actual \\ Predicted | bullish | bearish | neutral |",
        "|---|---|---|---|",
    ]

    cm = metrics["confusion_matrix"]
    for actual in ["bullish", "bearish", "neutral"]:
        row = cm[actual]
        lines.append(f"| **{actual}** | {row['bullish']} | {row['bearish']} | {row['neutral']} |")

    lines.extend([
        "",
        "## Error Analysis",
        "",
    ])

    errors = metrics.get("errors", [])
    if not errors:
        lines.append("No errors.")
    else:
        for err in errors:
            lines.append(
                f"- **{err['excerpt_id']}**: expected {err['expected']}, "
                f"got {err['predicted']} — {err['description']}"
            )

    lines.extend([
        "",
        "## Improvement Suggestions",
        "",
        "- Add more context via RAG (historical price data, recent news) to improve scoring accuracy",
        "- Use few-shot examples in prompts for ambiguous cases (mixed signals, neutral)",
        "- Implement confidence calibration using temperature scaling",
        "- Add multi-turn analysis for complex scenarios with competing signals",
    ])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
