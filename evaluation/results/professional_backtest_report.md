# Professional Backtest Report

*Level C evaluation: walk-forward, calibration, baselines, statistical tests, and P&L simulation.*

## 1. Dataset & methodology

- **Total events**: 144 (2018–2024)
- **Commodities covered**: copper, corn, crude_oil_brent, crude_oil_wti, gold, natural_gas, silver, wheat
- **Train**: 61 events (2018-01-31 → 2021-11-26)
- **Calibration**: 26 events (2022-02-24 → 2022-12-14)
- **Test**: 57 events (2023-01-09 → 2024-12-18)

**Split logic:** train < 2022-01-01 · calibration 2022 · test ≥ 2023-01-01. LLM, calibration, and thresholds are fitted ONLY on train+calibration. All final metrics are on the hold-out test split — never seen before.

**Ground truth:**
- `expected_direction` — what an expert analyst would have predicted from the news text alone.
- `actual_direction_d{h}` — derived from real Yahoo Finance close price at d0 vs. d{h}, with |change| < 0.5% counted as neutral.

## 2. Headline metrics (test split, horizon = 7 trading days)

| Method | Accuracy vs. market | 95% CI | vs. label |
|---|---|---|---|
| baseline:random | 24.6% | [12.3%, 36.8%] | 31.6% |
| baseline:always_bullish | 47.4% | [35.1%, 61.4%] | 71.9% |
| baseline:keyword | 26.3% | [15.8%, 38.6%] | 43.9% |

> n = 57 evaluable events. CI is bootstrap-estimated over 1000 resamples. A baseline random-ternary classifier is 33%.

## 4. Confidence calibration

*(Calibration requires LLM predictions on both calibration and test splits. Run `python -m evaluation.walk_forward --split calibration` and `--split test` first.)*

## 5. Per-commodity accuracy (test split, d7)

| Commodity | LLM n | LLM acc | Keyword acc |
|---|---|---|---|
| copper | 0 | — | 14.3% |
| corn | 0 | — | 0.0% |
| crude_oil_brent | 0 | — | 62.5% |
| crude_oil_wti | 0 | — | 50.0% |
| gold | 0 | — | 24.0% |
| natural_gas | 0 | — | 0.0% |
| silver | 0 | — | 0.0% |
| wheat | 0 | — | 0.0% |

## 6. Multi-horizon accuracy (test split)

| Method | d1 | d3 | d7 | d14 | d30 |
|---|---|---|---|---|---|
| baseline:random | 21.1% | 36.8% | 24.6% | 38.6% | 33.3% |
| baseline:always_bullish | 28.1% | 33.3% | 47.4% | 43.9% | 49.1% |
| baseline:keyword | 31.6% | 28.1% | 26.3% | 31.6% | 29.8% |

## 7. Confusion matrix (LLM, test split)

## 8. P&L simulation (LLM, test split)

## 9. Honest limitations

- **Sample size**: 144 events total; ~60–70 on the test split. Power is limited — differences < ~10% accuracy points may not be statistically significant.
- **Hindsight in labels**: `expected_direction` was curated post-hoc. The **actual-market direction** is the objective truth used in all metrics and P&L.
- **Market-moving events bias**: the dataset is skewed toward *newsworthy* events — real-world news streams contain much more noise where the correct prediction is often neutral.
- **No cost modelling**: P&L is gross of transaction costs.
- **One news text per event**: production systems consume text continuously and can average multiple signals.

*Report generated: 2026-04-18T23:00:00*
