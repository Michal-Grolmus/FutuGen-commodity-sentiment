"""Statistical tests for backtest metrics.

- Bootstrap 95% CI on any metric
- Binomial two-sided p-value vs. random baseline (33%)
- McNemar's test for paired model comparison (did model A beat model B?)
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable


def bootstrap_ci(
    values: list[float],
    metric_fn: Callable[[list[float]], float],
    n_iter: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Bootstrap CI for a metric on a list of values.

    Returns (point_estimate, lower_bound, upper_bound).
    """
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    point = metric_fn(values)
    draws = []
    n = len(values)
    for _ in range(n_iter):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        draws.append(metric_fn(sample))
    draws.sort()
    alpha = (1.0 - confidence) / 2.0
    low = draws[int(alpha * n_iter)]
    high = draws[int((1.0 - alpha) * n_iter)]
    return point, low, high


def accuracy(labels: list[float]) -> float:
    """Mean of 1/0 correctness labels."""
    if not labels:
        return 0.0
    return sum(labels) / len(labels)


def binomial_two_sided_pvalue(successes: int, trials: int, p_null: float) -> float:
    """Two-sided binomial p-value: probability of observing >= |successes - expected|
    successes under H0 of Bernoulli(p_null).

    Implemented with exact binomial PMF (no scipy).
    """
    if trials == 0:
        return 1.0
    expected = trials * p_null
    deviation = abs(successes - expected)

    pmf = [math.comb(trials, k) * (p_null ** k) * ((1 - p_null) ** (trials - k))
           for k in range(trials + 1)]
    # two-sided: sum probabilities of outcomes at least as extreme
    pval = sum(p for k, p in enumerate(pmf) if abs(k - expected) >= deviation)
    return min(1.0, pval)


def mcnemar_pvalue(
    both_correct: int,
    a_only: int,
    b_only: int,
    both_wrong: int,
) -> float:
    """McNemar's test for paired model comparison.

    Tests H0: model A and model B have same error rate.
    Uses the continuity-corrected chi-square approximation for b + c >= 25,
    exact binomial for smaller samples.
    """
    del both_correct, both_wrong  # unused but kept for clarity
    n = a_only + b_only
    if n == 0:
        return 1.0
    if n < 25:
        # Exact binomial: count of "a_only" under Binomial(n, 0.5)
        k = min(a_only, b_only)
        pmf = [math.comb(n, i) * (0.5 ** n) for i in range(n + 1)]
        pval = 2.0 * sum(pmf[i] for i in range(k + 1))
        return min(1.0, pval)
    # Continuity-corrected chi-square (df=1)
    chi2 = (abs(a_only - b_only) - 1) ** 2 / n
    # chi-square(1 df) upper-tail: erfc(sqrt(chi2/2))
    return math.erfc(math.sqrt(chi2 / 2.0))


def confusion_matrix(
    predictions: list[dict],
    truth_key: str = "expected_direction",
    pred_key: str = "direction",
) -> dict[str, dict[str, int]]:
    """Build 3x3 confusion matrix {actual: {predicted: count}}."""
    labels = ["bullish", "bearish", "neutral"]
    cm: dict[str, dict[str, int]] = {a: {p: 0 for p in labels} for a in labels}
    for p in predictions:
        actual = p.get(truth_key, "neutral")
        predicted = p.get(pred_key, "neutral")
        if actual not in cm or predicted not in cm[actual]:
            continue
        cm[actual][predicted] += 1
    return cm


def paired_correctness(
    preds_a: list[dict],
    preds_b: list[dict],
    truth_key: str = "expected_direction",
    pred_key: str = "direction",
) -> tuple[int, int, int, int]:
    """For two models evaluated on the same events, return McNemar cells.

    Returns (both_correct, a_only_correct, b_only_correct, both_wrong).
    Assumes preds_a and preds_b are aligned by position.
    """
    if len(preds_a) != len(preds_b):
        raise ValueError("Predictions must be aligned (same length, same order).")
    bc = ac = bc_only = bw = 0
    for a, b in zip(preds_a, preds_b, strict=False):
        a_right = a.get(pred_key) == a.get(truth_key)
        b_right = b.get(pred_key) == b.get(truth_key)
        if a_right and b_right:
            bc += 1
        elif a_right and not b_right:
            ac += 1
        elif b_right and not a_right:
            bc_only += 1
        else:
            bw += 1
    return bc, ac, bc_only, bw
