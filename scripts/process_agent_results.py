"""Process agent evaluation results and generate real evaluation report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from evaluation.dataset import compute_metrics, evaluate_prediction, generate_report, load_test_set
from src.models import CommoditySignal

# All 12 agent results from Claude evaluation
AGENT_RESULTS = [
    {"excerpt_id": "opec_01", "signals": [
        {"commodity": "crude_oil_wti", "display_name": "WTI Crude Oil", "direction": "bullish", "confidence": 0.85,
         "rationale": "A 1M bpd OPEC production cut directly reduces global supply — a strong upward price catalyst.",
         "timeframe": "medium_term", "source_text": "production cut of one million barrels per day", "speaker": None},
        {"commodity": "crude_oil_brent", "display_name": "Brent Crude Oil", "direction": "bullish", "confidence": 0.85,
         "rationale": "OPEC cuts tighten the global supply balance, with Brent directly impacted.",
         "timeframe": "medium_term", "source_text": "production cut of one million barrels per day", "speaker": None},
    ]},
    {"excerpt_id": "fed_01", "signals": [
        {"commodity": "gold", "display_name": "Gold", "direction": "bearish", "confidence": 0.7,
         "rationale": "Higher interest rates increase the opportunity cost of holding gold and strengthen the dollar.",
         "timeframe": "short_term", "source_text": "raised interest rates by 25 basis points", "speaker": None},
    ]},
    {"excerpt_id": "fed_02", "signals": [
        {"commodity": "gold", "display_name": "Gold", "direction": "bullish", "confidence": 0.75,
         "rationale": "Rate cuts reduce real yields and weaken the dollar, both strong tailwinds for gold.",
         "timeframe": "medium_term", "source_text": "pause interest rate increases", "speaker": None},
        {"commodity": "silver", "display_name": "Silver", "direction": "bullish", "confidence": 0.65,
         "rationale": "Silver benefits from the same dovish monetary pivot as gold.",
         "timeframe": "medium_term", "source_text": "two rate cuts by year end", "speaker": None},
    ]},
    {"excerpt_id": "weather_01", "signals": [
        {"commodity": "corn", "display_name": "Corn", "direction": "bullish", "confidence": 0.85,
         "rationale": "Extreme drought in major corn states with 15-year low soil moisture threatens supply.",
         "timeframe": "medium_term", "source_text": "extreme drought warning across US Midwest", "speaker": None},
        {"commodity": "wheat", "display_name": "Wheat", "direction": "bullish", "confidence": 0.80,
         "rationale": "Severe drought in key wheat states threatens yields at critical growing period.",
         "timeframe": "medium_term", "source_text": "yield reductions of 20-30%", "speaker": None},
    ]},
    {"excerpt_id": "sanctions_01", "signals": [
        {"commodity": "natural_gas", "display_name": "Natural Gas", "direction": "bullish", "confidence": 0.85,
         "rationale": "Complete EU ban on Russian LNG removing ~15% of European gas supply is a major shock.",
         "timeframe": "medium_term", "source_text": "ban on Russian LNG imports", "speaker": None},
        {"commodity": "crude_oil_brent", "display_name": "Brent Crude Oil", "direction": "bullish", "confidence": 0.55,
         "rationale": "Stricter oil price cap enforcement could modestly tighten global crude supply.",
         "timeframe": "short_term", "source_text": "stricter enforcement of oil price cap", "speaker": None},
    ]},
    {"excerpt_id": "china_01", "signals": [
        {"commodity": "copper", "display_name": "Copper", "direction": "bullish", "confidence": 0.75,
         "rationale": "China PMI at 52.3 signals robust manufacturing expansion; China is largest copper consumer.",
         "timeframe": "medium_term", "source_text": "PMI came in at 52.3", "speaker": None},
    ]},
    {"excerpt_id": "inflation_01", "signals": [
        {"commodity": "gold", "display_name": "Gold", "direction": "bullish", "confidence": 0.8,
         "rationale": "CPI at 4.1% significantly exceeded 3.6% expectation. Gold is the primary inflation hedge.",
         "timeframe": "medium_term", "source_text": "CPI rose 4.1% year over year", "speaker": None},
        {"commodity": "silver", "display_name": "Silver", "direction": "bullish", "confidence": 0.6,
         "rationale": "Silver benefits as a secondary inflation hedge when CPI surprises to the upside.",
         "timeframe": "medium_term", "source_text": "inflation hedges", "speaker": None},
    ]},
    {"excerpt_id": "inventory_01", "signals": [
        {"commodity": "crude_oil_wti", "display_name": "WTI Crude Oil", "direction": "bearish", "confidence": 0.85,
         "rationale": "Inventory build of 8.2M barrels exceeded expectations by 4x, indicating demand weakness.",
         "timeframe": "short_term", "source_text": "inventory build of 8.2 million barrels", "speaker": None},
    ]},
    {"excerpt_id": "geopolitical_01", "signals": [
        {"commodity": "crude_oil_brent", "display_name": "Brent Crude Oil", "direction": "bullish", "confidence": 0.9,
         "rationale": "Attacks on tankers in Strait of Hormuz (20% of global oil trade) are a severe supply risk.",
         "timeframe": "short_term", "source_text": "attacks on shipping in Strait of Hormuz", "speaker": None},
        {"commodity": "crude_oil_wti", "display_name": "WTI Crude Oil", "direction": "bullish", "confidence": 0.75,
         "rationale": "Hormuz disruptions elevate global crude prices, pulling WTI higher via arbitrage.",
         "timeframe": "short_term", "source_text": "tensions in the Middle East", "speaker": None},
    ]},
    {"excerpt_id": "neutral_01", "signals": []},
    {"excerpt_id": "mining_01", "signals": [
        {"commodity": "copper", "display_name": "Copper", "direction": "bullish", "confidence": 0.8,
         "rationale": "Production halt at Escondida (~5% of global copper supply) is significant supply disruption.",
         "timeframe": "short_term", "source_text": "5% of global copper output halted", "speaker": None},
    ]},
    {"excerpt_id": "mixed_01", "signals": [
        {"commodity": "gold", "display_name": "Gold", "direction": "neutral", "confidence": 0.6,
         "rationale": "Opposing pressures: strong dollar (bearish) vs geopolitical tensions (bullish). Neither dominates.",
         "timeframe": "short_term", "source_text": "gold caught between competing forces", "speaker": None},
    ]},
]


def main() -> None:
    test_set = load_test_set("evaluation/test_set.json")
    gt_map = {gt.excerpt_id: gt for gt in test_set}

    predictions = []
    for result in AGENT_RESULTS:
        eid = result["excerpt_id"]
        gt = gt_map[eid]
        signals = [CommoditySignal(**s) for s in result["signals"]]
        pred = evaluate_prediction(signals, gt)
        predictions.append(pred)

        best = max(signals, key=lambda s: s.confidence).direction.value if signals else "neutral"
        status = "CORRECT" if pred.direction_correct else "WRONG"
        print(f"  [{status}] {eid}: expected={gt.expected_direction.value}, got={best}, "
              f"recall={pred.commodity_recall:.0%}")

    metrics = compute_metrics(predictions)
    print(f"\n=== RESULTS ===")
    print(f"Direction accuracy: {metrics['direction_accuracy']:.1%}")
    print(f"Avg commodity recall: {metrics['avg_commodity_recall']:.1%}")
    print(f"Errors: {len(metrics['errors'])}")

    # Generate report
    Path("evaluation/results").mkdir(parents=True, exist_ok=True)
    generate_report(metrics, "evaluation/results/evaluation_report.md")
    print(f"\nReport: evaluation/results/evaluation_report.md")

    # Save predictions
    with open("evaluation/results/predictions.json", "w", encoding="utf-8") as f:
        json.dump([p.model_dump(mode="json") for p in predictions], f, indent=2, ensure_ascii=False)
    print(f"Predictions: evaluation/results/predictions.json")


if __name__ == "__main__":
    main()
