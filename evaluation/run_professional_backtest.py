"""Professional backtest orchestrator.

Pipeline:
  1. Load enriched events (dates, news_text, expected_direction, prices{d0..d30}).
  2. Split by date: train / calibration / test (point-in-time, no leakage).
  3. Run baselines (random, always_bullish, keyword) on calibration and test.
  4. Load LLM predictions from `evaluation/results/predictions_llm_{split}.json`
     (run `python -m evaluation.walk_forward --split ...` first).
  5. Grade everything (vs. analyst label + vs. actual market move per horizon).
  6. Fit confidence calibration on LLM calibration split.
  7. Apply calibration to LLM test split.
  8. Compute metrics + bootstrap 95% CI per method.
  9. McNemar test: LLM (calibrated) vs. each baseline.
 10. Per-commodity + per-horizon breakdown.
 11. P&L simulation over multiple horizons/thresholds.
 12. Render reliability diagram as SVG.
 13. Write Markdown report.

Idempotent: skips LLM calls, only reads cached predictions.

Usage:
    python -m evaluation.run_professional_backtest
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from evaluation.baselines import BASELINES, run_baseline
from evaluation.calibration import (
    apply_calibration,
    expected_calibration_error,
    fit_calibration,
    save_calibration,
)
from evaluation.grade import HORIZONS, grade
from evaluation.horizon_analysis import analyze_all as horizon_analyze
from evaluation.pnl import simulate
from evaluation.reliability import reliability_diagram_svg
from evaluation.splits import SplitConfig, describe_split, split_events
from evaluation.statistics import (
    accuracy as acc_metric,
)
from evaluation.statistics import (
    bootstrap_ci,
    confusion_matrix,
    mcnemar_pvalue,
    paired_correctness,
)

ROOT = Path(__file__).resolve().parent.parent
EVENTS_PATH = ROOT / "evaluation" / "historical_events_enriched.json"
RESULTS_DIR = ROOT / "evaluation" / "results"
REPORT_PATH = RESULTS_DIR / "professional_backtest_report.md"
RELIABILITY_SVG_PATH = RESULTS_DIR / "reliability_llm_test.svg"
RELIABILITY_CAL_SVG_PATH = RESULTS_DIR / "reliability_llm_calibration.svg"
CALIBRATION_PATH = RESULTS_DIR / "calibration.json"
GRADED_RESULTS_PATH = RESULTS_DIR / "graded_test.json"
SUMMARY_JSON_PATH = RESULTS_DIR / "professional_summary.json"

PNL_HORIZONS = [1, 3, 7, 14, 30]
PNL_THRESHOLDS = [0.50, 0.60, 0.70, 0.80]
PRIMARY_HORIZON = 7  # focus horizon for top-line metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_events() -> list[dict[str, Any]]:
    with open(EVENTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def try_load_llm_predictions(split: str) -> list[dict[str, Any]] | None:
    path = RESULTS_DIR / f"predictions_llm_{split}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    preds = data.get("predictions", data) if isinstance(data, dict) else data
    if not isinstance(preds, list):
        return None
    return preds


def metrics_for_predictions(
    graded: list[dict[str, Any]],
    horizon: int,
) -> dict[str, Any]:
    """Accuracy vs. label + vs. market at given horizon, with bootstrap CI."""
    label_correct = [1.0 if g.get("correct_label") else 0.0 for g in graded]
    market_key = f"correct_market_d{horizon}"
    market_correct = [1.0 if g.get(market_key) else 0.0 for g in graded
                      if g.get(market_key) is not None]

    label_point, label_lo, label_hi = bootstrap_ci(label_correct, acc_metric)
    if market_correct:
        market_point, market_lo, market_hi = bootstrap_ci(market_correct, acc_metric)
    else:
        market_point = market_lo = market_hi = 0.0

    return {
        "count": len(graded),
        "evaluable_market": len(market_correct),
        "accuracy_vs_label": {
            "point": label_point,
            "ci95_low": label_lo,
            "ci95_high": label_hi,
        },
        "accuracy_vs_market": {
            "point": market_point,
            "ci95_low": market_lo,
            "ci95_high": market_hi,
        },
    }


def per_commodity_accuracy(graded: list[dict[str, Any]], horizon: int) -> dict[str, dict[str, Any]]:
    by_commodity: dict[str, list[dict[str, Any]]] = {}
    for g in graded:
        by_commodity.setdefault(g["commodity"], []).append(g)
    out = {}
    for com, gs in sorted(by_commodity.items()):
        evaluable = [g for g in gs if g.get(f"correct_market_d{horizon}") is not None]
        if not evaluable:
            out[com] = {"count": 0, "accuracy": None}
            continue
        correct = sum(1 for g in evaluable if g[f"correct_market_d{horizon}"])
        out[com] = {
            "count": len(evaluable),
            "correct": correct,
            "accuracy": correct / len(evaluable),
        }
    return out


def grade_all(
    test_events: list[dict[str, Any]],
    calib_events: list[dict[str, Any]],
    llm_test: list[dict[str, Any]] | None,
    llm_calib: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Run baselines + grade both baseline and LLM predictions on both splits."""
    baseline_test: dict[str, list[dict[str, Any]]] = {}
    baseline_calib: dict[str, list[dict[str, Any]]] = {}

    for name in BASELINES:
        preds_test = run_baseline(name, test_events)
        preds_calib = run_baseline(name, calib_events)
        baseline_test[name] = grade(preds_test, test_events)
        baseline_calib[name] = grade(preds_calib, calib_events)

    llm_test_graded = grade(llm_test, test_events) if llm_test else None
    llm_calib_graded = grade(llm_calib, calib_events) if llm_calib else None

    return {
        "baseline_test": baseline_test,
        "baseline_calib": baseline_calib,
        "llm_test": llm_test_graded,
        "llm_calib": llm_calib_graded,
    }


def compare_pair(
    preds_a: list[dict[str, Any]],
    preds_b: list[dict[str, Any]],
    horizon: int,
) -> dict[str, Any]:
    """McNemar test on two paired predictions. Uses correct_market_d{horizon}."""
    # Align by event_id
    b_by_id = {p["event_id"]: p for p in preds_b}
    paired_a, paired_b = [], []
    for p in preds_a:
        if p["event_id"] in b_by_id:
            other = b_by_id[p["event_id"]]
            key = f"correct_market_d{horizon}"
            if p.get(key) is None or other.get(key) is None:
                continue
            paired_a.append({"direction": "x", "expected_direction": "y" if p[key] else "x"})
            paired_b.append({"direction": "x", "expected_direction": "y" if other[key] else "x"})
    # paired_correctness uses direction vs expected_direction to determine "correct"
    # We encode correctness into the pairing via the y/x trick above.
    bc, a_only, b_only, bw = paired_correctness(paired_a, paired_b)
    pval = mcnemar_pvalue(bc, a_only, b_only, bw)
    return {
        "both_correct": bc,
        "a_only_correct": a_only,
        "b_only_correct": b_only,
        "both_wrong": bw,
        "n_paired": bc + a_only + b_only + bw,
        "p_value": pval,
    }


def markdown_report(summary: dict[str, Any]) -> str:
    """Compose the Markdown report from the summary dict."""
    out: list[str] = []
    out.append("# Professional Backtest Report\n")
    out.append("*Level C evaluation: walk-forward, calibration, baselines, statistical tests, and P&L simulation.*\n")

    # --- Dataset & split ---
    out.append("## 1. Dataset & methodology\n")
    ds = summary["dataset"]
    out.append(f"- **Total events**: {ds['total']} (2018–2024)")
    out.append(f"- **Commodities covered**: {', '.join(ds['commodities'])}")
    split = ds["split"]
    for name in ("train", "calibration", "test"):
        s = split[name]
        if s["count"] == 0:
            out.append(f"- **{name.capitalize()}**: 0 events")
        else:
            out.append(f"- **{name.capitalize()}**: {s['count']} events "
                       f"({s['date_min']} → {s['date_max']})")
    out.append("")
    out.append("**Split logic:** train < 2022-01-01 · calibration 2022 · test ≥ 2023-01-01. "
               "LLM, calibration, and thresholds are fitted ONLY on train+calibration. "
               "All final metrics are on the hold-out test split — never seen before.")
    out.append("")
    out.append("**Ground truth:**")
    out.append("- `expected_direction` — what an expert analyst would have predicted from the news text alone.")
    out.append("- `actual_direction_d{h}` — derived from real Yahoo Finance close price "
               f"at d0 vs. d{{h}}, with |change| < {0.5:.1f}% counted as neutral.")
    out.append("")

    # --- Headline metrics ---
    out.append(f"## 2. Headline metrics (test split, horizon = {PRIMARY_HORIZON} trading days)\n")
    out.append("| Method | Accuracy vs. market | 95% CI | vs. label |")
    out.append("|---|---|---|---|")
    for name, row in summary["methods"].items():
        m = row["metrics_test"][f"d{PRIMARY_HORIZON}"]
        m_label = row["metrics_test"][f"d{PRIMARY_HORIZON}"]["accuracy_vs_label"]
        label = name if not row.get("note") else f"{name} *({row['note']})*"
        out.append(
            f"| {label} | {m['accuracy_vs_market']['point']:.1%} "
            f"| [{m['accuracy_vs_market']['ci95_low']:.1%}, {m['accuracy_vs_market']['ci95_high']:.1%}] "
            f"| {m_label['point']:.1%} |"
        )
    out.append("")
    first_method = next(iter(summary["methods"]))
    n_evaluable = summary["methods"][first_method]["metrics_test"][f"d{PRIMARY_HORIZON}"]["evaluable_market"]
    out.append(f"> n = {n_evaluable} evaluable events. "
               f"CI is bootstrap-estimated over {summary['bootstrap_iters']} resamples. "
               "A baseline random-ternary classifier is 33%.")
    out.append("")

    # --- Statistical comparison ---
    if summary.get("comparisons"):
        out.append("## 3. Statistical comparisons vs. baselines\n")
        out.append("Did the LLM beat each baseline on the hold-out test split? "
                   "Uses McNemar's exact test on paired predictions at "
                   f"d{PRIMARY_HORIZON}.\n")
        out.append("| Comparison | Both right | LLM only | Baseline only | Both wrong | p-value | Verdict |")
        out.append("|---|---|---|---|---|---|---|")
        for label, cmp in summary["comparisons"].items():
            verdict = "LLM wins" if cmp["p_value"] < 0.05 and cmp["a_only_correct"] > cmp["b_only_correct"] else (
                "baseline wins" if cmp["p_value"] < 0.05 else "tie / not significant")
            out.append(
                f"| {label} | {cmp['both_correct']} | {cmp['a_only_correct']} | "
                f"{cmp['b_only_correct']} | {cmp['both_wrong']} | {cmp['p_value']:.3f} | {verdict} |"
            )
        out.append("")

    # --- Calibration ---
    out.append("## 4. Confidence calibration\n")
    cal = summary.get("calibration")
    if cal:
        out.append(f"- **Raw ECE (calibration split)**: {cal['ece_before']:.3f}")
        out.append(f"- **Calibrated ECE (test split)**: {cal['ece_after_test']:.3f}")
        out.append(f"- **Calibration samples**: {cal['n_calibration']} events")
        out.append("")
        out.append("The calibration is bin-based (10 bins of 0.1 width). Each bin's empirical "
                   "accuracy on the **calibration split** is used as the lookup for the raw "
                   "confidence at test time. This remaps over-confident buckets down and "
                   "under-confident buckets up, so calibrated_confidence ≈ expected_accuracy.")
        out.append("")
        out.append(f"See `{RELIABILITY_CAL_SVG_PATH.name}` (calibration split) and "
                   f"`{RELIABILITY_SVG_PATH.name}` (test split) for reliability diagrams.")
        out.append("")
    else:
        out.append("*(Calibration requires LLM predictions on both calibration and test splits. "
                   "Run `python -m evaluation.walk_forward --split calibration` and "
                   "`--split test` first.)*")
        out.append("")

    # --- Per-commodity ---
    out.append(f"## 5. Per-commodity accuracy (test split, d{PRIMARY_HORIZON})\n")
    per_com = summary.get("per_commodity", {})
    if per_com:
        llm_rows = per_com.get("llm") or {}
        kw_rows = per_com.get("keyword") or {}
        out.append("| Commodity | LLM n | LLM acc | Keyword acc |")
        out.append("|---|---|---|---|")
        commodities = sorted(set(llm_rows.keys()) | set(kw_rows.keys()))
        for com in commodities:
            llm_row = llm_rows.get(com, {})
            kw_row = kw_rows.get(com, {})
            llm_acc = f"{llm_row['accuracy']:.1%}" if llm_row.get("accuracy") is not None else "—"
            kw_acc = f"{kw_row['accuracy']:.1%}" if kw_row.get("accuracy") is not None else "—"
            out.append(f"| {com} | {llm_row.get('count', 0)} | {llm_acc} | {kw_acc} |")
        out.append("")

    # --- Horizons ---
    out.append("## 6. Multi-horizon accuracy (test split)\n")
    out.append("| Method | d1 | d3 | d7 | d14 | d30 |")
    out.append("|---|---|---|---|---|---|")
    for name, row in summary["methods"].items():
        cells = [name]
        for h in HORIZONS:
            m = row["metrics_test"].get(f"d{h}", {}).get("accuracy_vs_market")
            cells.append(f"{m['point']:.1%}" if m else "—")
        out.append("| " + " | ".join(cells) + " |")
    out.append("")

    # --- Confusion matrix ---
    out.append("## 7. Confusion matrix (LLM, test split)\n")
    cm = summary.get("confusion_matrix_llm") or {}
    if cm:
        out.append("| actual ↓ \\ predicted → | bullish | bearish | neutral |")
        out.append("|---|---|---|---|")
        for actual in ("bullish", "bearish", "neutral"):
            row = cm.get(actual, {})
            out.append(f"| **{actual}** | {row.get('bullish', 0)} | "
                       f"{row.get('bearish', 0)} | {row.get('neutral', 0)} |")
        out.append("")

    # --- P&L ---
    out.append("## 8. P&L simulation (LLM, test split)\n")
    pnl = summary.get("pnl") or {}
    if pnl:
        out.append("| Horizon | Threshold | Trades | Total log-return | Sharpe | Max drawdown | Win rate |")
        out.append("|---|---|---|---|---|---|---|")
        for row in pnl:
            sharpe = f"{row['sharpe']:.2f}" if row.get("sharpe") is not None else "—"
            wr = f"{row['win_rate']:.1%}" if row.get("win_rate") is not None else "—"
            out.append(
                f"| d{row['horizon_days']} | {row['confidence_threshold']:.2f} | {row['trades']} | "
                f"{row['total_return']:.3f} | {sharpe} | {row['max_drawdown']:.3f} | {wr} |"
            )
        out.append("")
        out.append("> **Caveats**: No transaction costs, no slippage, 1-unit equal-weight per trade, "
                   "overlapping positions allowed. Figures are gross, not net. A realistic futures cost "
                   "assumption of ~0.05–0.15% per round-trip would erode Sharpe noticeably.")
        out.append("")

    # --- Horizon analysis ---
    ha = summary.get("horizon_analysis")
    if ha:
        out.append("## 9. Horizon analysis — is the clock wrong, not the direction?\n")
        out.append(f"*Source: {ha.get('source', 'unknown')}*\n")
        out.append("Different event types react on different timescales — a supply "
                   "shock spikes + reverts in days, a Fed pivot takes weeks to price in. "
                   "Fixed-d7 evaluation can under-count predictions that were directionally "
                   "correct but evaluated at the wrong clock.\n")

        any_hit = ha.get("any_horizon", {})
        all_hit = ha.get("all_horizons", {})
        out.append("### Upper / lower bounds on hit rate\n")
        out.append(f"- **Any-horizon hit rate** (correct at d1 OR d3 OR d7 OR d14 OR d30): "
                   f"**{any_hit.get('any_hit', 0):.1%}** — loose upper bound.")
        out.append(f"- **All-horizons hit rate** (correct at every horizon — durable signal): "
                   f"**{all_hit.get('all_hit', 0):.1%}** — tight lower bound.")
        out.append("- Gap between them = predictions whose direction was right but "
                   "*timing-dependent*. Large gap → pick better horizon; small gap → "
                   "signal is stable or universally wrong.\n")

        persist = ha.get("signal_persistence", {})
        if persist and persist.get("base_n_d1_correct"):
            out.append("### Signal persistence P(correct at d_h | correct at d1)\n")
            out.append("| Horizon | Still correct |")
            out.append("|---|---|")
            for h in HORIZONS:
                v = persist.get(f"d{h}_given_d1")
                out.append(f"| d{h} | {v:.1%} |" if v is not None else f"| d{h} | — |")
            out.append("")
            out.append("> ~1.0 = durable; 0.5 = the signal is already half reverted by "
                       "that horizon; <0.5 = trade flipped against you.\n")

        ttp = ha.get("time_to_peak", {})
        if ttp and ttp.get("n"):
            dist = ttp.get("distribution", {})
            out.append("### Time-to-peak distribution\n")
            out.append(f"- Mean peak horizon: **d{ttp.get('mean_peak_horizon', 0):.1f}** "
                       f"({ttp.get('n', 0)} directional trades).")
            bar_rows = " | ".join(f"{k}: {v}" for k, v in dist.items())
            out.append(f"- Distribution: {bar_rows}")
            out.append("")

        mae_mfe = ha.get("mae_mfe", {})
        if mae_mfe and mae_mfe.get("n"):
            ratio_val = mae_mfe.get('ratio_mfe_mae')
            ratio = f"{ratio_val:.2f}" if ratio_val is not None else "—"
            out.append("### Maximum Favorable / Adverse Excursion\n")
            out.append(f"- **Avg MFE** (best the average trade got to): "
                       f"**{mae_mfe.get('avg_mfe_pct', 0):+.2f}%**")
            out.append(f"- **Avg MAE** (worst the average trade dropped to): "
                       f"**{mae_mfe.get('avg_mae_pct', 0):+.2f}%**")
            out.append(f"- **MFE/|MAE|** ratio: **{ratio}** — > 1.5 indicates "
                       "asymmetric payoff (good); < 1 means average drawdown exceeds "
                       "average upside.")
            out.append("")

        opt = ha.get("optimal_horizon_per_type", {})
        if opt:
            out.append("### Optimal horizon per event type *(learned on train+cal)*\n")
            out.append("| Event type | Best horizon | Accuracy | n (train+cal) |")
            out.append("|---|---|---|---|")
            for et, row in sorted(opt.items(), key=lambda x: -x[1]["n_samples"]):
                out.append(f"| {et} | d{row['best_horizon']} | "
                           f"{row['best_accuracy']:.1%} | {row['n_samples']} |")
            out.append("")

        adap = ha.get("adaptive_vs_fixed", {})
        if adap and adap.get("n"):
            uplift = adap.get("uplift", 0)
            verdict = "adaptive wins" if uplift > 0.02 else (
                "fixed-d7 wins" if uplift < -0.02 else "no meaningful difference")
            out.append("### Adaptive horizon vs. fixed d=7 (test split)\n")
            out.append(f"- **Fixed d=7 accuracy**: {adap.get('fixed_d7_accuracy', 0):.1%}")
            out.append(f"- **Adaptive (per-type horizon learned on train+cal)**: "
                       f"{adap.get('adaptive_accuracy', 0):.1%}")
            out.append(f"- **Uplift**: {uplift:+.1%} → *{verdict}*")
            out.append("")
            out.append("> A positive uplift means **failing predictions at d=7 were often "
                       "correct at another horizon matching their event type**. A zero or "
                       "negative uplift means fixed-d7 is already close to optimal.\n")

    # --- Limitations ---
    out.append("## 10. Honest limitations\n")
    out.append("- **Sample size**: 387 events total; ~140 on the test split. "
               "Power is limited — differences < ~8% accuracy points may not be statistically significant.")
    out.append("- **Hindsight in labels**: `expected_direction` was curated post-hoc. "
               "The **actual-market direction** is the objective truth used in all metrics and P&L.")
    out.append("- **Market-moving events bias**: the dataset is skewed toward *newsworthy* events — "
               "real-world news streams contain much more noise where the correct prediction is often neutral.")
    out.append("- **No cost modelling**: P&L is gross of transaction costs.")
    out.append("- **One news text per event**: production systems consume text continuously and "
               "can average multiple signals.")
    out.append("")

    out.append(f"*Report generated: {summary.get('generated_at', '—')}*\n")
    return "\n".join(out)


def main() -> None:  # noqa: PLR0915
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    events = load_events()
    train, calib, test = split_events(events, SplitConfig())
    split_summary = describe_split(train, calib, test)
    logger.info("Split: %s", json.dumps(split_summary))

    llm_test = try_load_llm_predictions("test")
    llm_calib = try_load_llm_predictions("calibration")

    if llm_test is None:
        logger.warning("No LLM test predictions found at %s. "
                       "Run `python -m evaluation.walk_forward --split test` first.",
                       RESULTS_DIR / "predictions_llm_test.json")
    if llm_calib is None:
        logger.warning("No LLM calibration predictions found. "
                       "Run `python -m evaluation.walk_forward --split calibration`.")

    graded = grade_all(test, calib, llm_test, llm_calib)

    methods: dict[str, Any] = {}
    per_commodity: dict[str, Any] = {}

    # Baselines
    for name, graded_test in graded["baseline_test"].items():
        metrics_per_horizon = {f"d{h}": metrics_for_predictions(graded_test, h) for h in HORIZONS}
        methods[f"baseline:{name}"] = {
            "kind": "baseline",
            "metrics_test": metrics_per_horizon,
        }
    per_commodity["keyword"] = per_commodity_accuracy(
        graded["baseline_test"].get("keyword", []), PRIMARY_HORIZON,
    )

    # LLM (raw)
    calibration_obj: dict[str, Any] | None = None
    ece_before = ece_after_test = None
    if graded["llm_test"]:
        raw_metrics = {f"d{h}": metrics_for_predictions(graded["llm_test"], h) for h in HORIZONS}
        methods["llm_raw"] = {
            "kind": "llm",
            "metrics_test": raw_metrics,
        }
        per_commodity["llm"] = per_commodity_accuracy(graded["llm_test"], PRIMARY_HORIZON)

    # Calibration (fit on llm_calib, apply to llm_test)
    if graded["llm_calib"]:
        fit_target_graded = [
            {**g, "expected_direction": g.get(f"actual_direction_d{PRIMARY_HORIZON}") or "neutral"}
            for g in graded["llm_calib"]
            if g.get(f"actual_direction_d{PRIMARY_HORIZON}") is not None
        ]
        calibration_obj = fit_calibration(fit_target_graded)
        save_calibration(calibration_obj, str(CALIBRATION_PATH))
        ece_before = expected_calibration_error(calibration_obj)
        RELIABILITY_CAL_SVG_PATH.write_text(
            reliability_diagram_svg(calibration_obj, title="LLM reliability — calibration split"),
            encoding="utf-8",
        )
        # Apply to test
        if graded["llm_test"]:
            test_graded_as_market = [
                {**g, "expected_direction": g.get(f"actual_direction_d{PRIMARY_HORIZON}") or "neutral"}
                for g in graded["llm_test"]
            ]
            calibrated_test = apply_calibration(test_graded_as_market, calibration_obj)
            # Re-fit diagnostic on test to measure post-calibration ECE
            # Build a "post-calibration" quasi-calibration object: bins defined on
            # calibrated_confidence → empirical accuracy on test
            test_as_preds_calibrated = [
                {
                    "direction": p["direction"],
                    "expected_direction": p["expected_direction"],
                    "confidence": p["calibrated_confidence"],
                }
                for p in calibrated_test
            ]
            post_cal_obj = fit_calibration(test_as_preds_calibrated)
            ece_after_test = expected_calibration_error(post_cal_obj)
            RELIABILITY_SVG_PATH.write_text(
                reliability_diagram_svg(post_cal_obj, title="LLM reliability — test split (post-calibration)"),
                encoding="utf-8",
            )

    # Comparisons (LLM vs baselines) via McNemar
    comparisons: dict[str, Any] = {}
    if graded["llm_test"]:
        for name in BASELINES:
            base_graded = graded["baseline_test"].get(name)
            if base_graded:
                comparisons[f"LLM vs {name}"] = compare_pair(
                    graded["llm_test"], base_graded, PRIMARY_HORIZON,
                )

    # Confusion matrix
    confusion_llm = None
    if graded["llm_test"]:
        # Construct "correctness" lookups with explicit labels
        cm_preds = [
            {
                "direction": g["direction"],
                "expected_direction": g.get(f"actual_direction_d{PRIMARY_HORIZON}") or "neutral",
            }
            for g in graded["llm_test"]
        ]
        confusion_llm = confusion_matrix(cm_preds)

    # P&L simulation (LLM, multiple horizons/thresholds)
    pnl_rows: list[dict[str, Any]] = []
    if graded["llm_test"]:
        events_by_id = {e["event_id"]: e for e in test}
        preds_list = [p for p in graded["llm_test"] if p["event_id"] in events_by_id]
        ordered_events = [events_by_id[p["event_id"]] for p in preds_list]
        for h in PNL_HORIZONS:
            for t in PNL_THRESHOLDS:
                sim = simulate(preds_list, ordered_events, horizon=h, threshold=t)
                pnl_rows.append({k: v for k, v in sim.items() if k != "trade_list"})

    # Horizon analysis: is a wrong d=7 prediction correct at d=1 or d=14?
    # Uses LLM test if available; otherwise falls back to keyword baseline so the
    # report has the methodology section even without an API key.
    horizon_report: dict[str, Any] | None = None
    test_for_horizon = graded["llm_test"]
    train_cal_for_horizon = graded["llm_calib"]
    horizon_source = "llm"
    if not test_for_horizon:
        test_for_horizon = graded["baseline_test"].get("keyword", [])
        train_cal_for_horizon = graded["baseline_calib"].get("keyword", [])
        horizon_source = "baseline:keyword (LLM predictions not available)"
    if test_for_horizon:
        horizon_report = horizon_analyze(test_for_horizon, train_cal_for_horizon, events)
        horizon_report["source"] = horizon_source

    # Final summary
    from datetime import datetime
    summary: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "bootstrap_iters": 1000,
        "dataset": {
            "total": len(events),
            "commodities": sorted({e["commodity"] for e in events}),
            "split": split_summary,
        },
        "methods": methods,
        "comparisons": comparisons,
        "confusion_matrix_llm": confusion_llm,
        "calibration": {
            "n_calibration": len(graded["llm_calib"]) if graded["llm_calib"] else 0,
            "ece_before": ece_before if ece_before is not None else 0.0,
            "ece_after_test": ece_after_test if ece_after_test is not None else 0.0,
        } if calibration_obj else None,
        "per_commodity": per_commodity,
        "pnl": pnl_rows,
        "horizon_analysis": horizon_report,
    }

    with open(SUMMARY_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    with open(GRADED_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "test": graded["llm_test"] or [],
            "baselines": graded["baseline_test"],
        }, f, indent=2, default=str)

    REPORT_PATH.write_text(markdown_report(summary), encoding="utf-8")
    logger.info("Report written: %s", REPORT_PATH.relative_to(ROOT))
    logger.info("Summary JSON: %s", SUMMARY_JSON_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
