"""Confidence calibration via reliability binning.

Approach: bin predictions by their raw confidence (0.0-1.0 in 10 bins of 0.1),
compute empirical accuracy in each bin on the CALIBRATION split, and remap
test-time confidence to the bin's empirical accuracy.

This is the most interpretable calibration: the calibrated confidence IS the
expected accuracy. Aligns with reliability diagram — if bin 0.8 has 55%
empirical accuracy, then a raw confidence of 0.8 is downgraded to 0.55.

For bins with too few samples (n < 5), we keep the raw confidence (can't
reliably estimate) and flag the bin. In a production system you'd use Platt
or isotonic regression; binning is honest for dataset sizes ~100-300.
"""
from __future__ import annotations

import json
from pathlib import Path

BIN_EDGES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0 + 1e-9]
MIN_SAMPLES_PER_BIN = 5


def _bin_index(confidence: float) -> int:
    for i in range(len(BIN_EDGES) - 1):
        if BIN_EDGES[i] <= confidence < BIN_EDGES[i + 1]:
            return i
    return len(BIN_EDGES) - 2


def fit_calibration(
    predictions: list[dict],
    truth_key: str = "expected_direction",
    pred_key: str = "direction",
    conf_key: str = "confidence",
) -> dict[str, object]:
    """Fit a bin-based calibration on a list of predictions with ground truth.

    Returns a calibration object storing per-bin empirical accuracy and counts.
    """
    bins: list[dict[str, object]] = []
    n_bins = len(BIN_EDGES) - 1
    for i in range(n_bins):
        bins.append({
            "bin_low": BIN_EDGES[i],
            "bin_high": min(BIN_EDGES[i + 1], 1.0),
            "count": 0,
            "correct": 0,
            "empirical_accuracy": None,
            "raw_mean_confidence": 0.0,
        })

    for p in predictions:
        conf = float(p.get(conf_key, 0.5))
        idx = _bin_index(conf)
        bins[idx]["count"] = int(bins[idx]["count"]) + 1  # type: ignore[assignment]
        if p.get(pred_key) == p.get(truth_key):
            bins[idx]["correct"] = int(bins[idx]["correct"]) + 1  # type: ignore[assignment]
        bins[idx]["raw_mean_confidence"] = float(bins[idx]["raw_mean_confidence"]) + conf  # type: ignore[assignment]

    for b in bins:
        count = int(b["count"])  # type: ignore[arg-type]
        if count >= MIN_SAMPLES_PER_BIN:
            b["empirical_accuracy"] = int(b["correct"]) / count  # type: ignore[arg-type]
            b["raw_mean_confidence"] = float(b["raw_mean_confidence"]) / count  # type: ignore[arg-type]
        else:
            b["empirical_accuracy"] = None
            b["raw_mean_confidence"] = 0.0 if count == 0 else float(b["raw_mean_confidence"]) / count  # type: ignore[arg-type]

    return {
        "bins": bins,
        "n_predictions": len(predictions),
        "min_samples_per_bin": MIN_SAMPLES_PER_BIN,
    }


def apply_calibration(
    predictions: list[dict],
    calibration: dict[str, object],
    conf_key: str = "confidence",
    out_key: str = "calibrated_confidence",
) -> list[dict]:
    """Remap raw confidence to calibrated confidence for each prediction.

    If a prediction falls into a bin with too few calibration samples,
    the raw confidence is kept unchanged.
    """
    bins = calibration["bins"]
    out = []
    for p in predictions:
        new = dict(p)
        conf = float(new.get(conf_key, 0.5))
        idx = _bin_index(conf)
        empirical = bins[idx]["empirical_accuracy"]  # type: ignore[index]
        new[out_key] = float(empirical) if empirical is not None else conf
        new["calibration_bin"] = idx
        out.append(new)
    return out


def save_calibration(calibration: dict[str, object], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2, ensure_ascii=False)


def load_calibration(path: str) -> dict[str, object]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def expected_calibration_error(calibration: dict[str, object]) -> float:
    """ECE: weighted absolute gap between empirical accuracy and mean confidence.

    Lower is better. Perfectly calibrated model has ECE = 0.
    """
    bins = calibration["bins"]
    total = sum(int(b["count"]) for b in bins)  # type: ignore[arg-type, index]
    if total == 0:
        return 0.0
    ece = 0.0
    for b in bins:
        count = int(b["count"])  # type: ignore[arg-type,index]
        empirical = b["empirical_accuracy"]  # type: ignore[index]
        if empirical is None or count == 0:
            continue
        raw_conf = float(b["raw_mean_confidence"])  # type: ignore[arg-type,index]
        ece += (count / total) * abs(float(empirical) - raw_conf)
    return ece
