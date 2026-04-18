# Professional Backtest Report

*Level C evaluation: walk-forward, calibration, baselines, statistical tests, and P&L simulation.*

## 1. Dataset & methodology

- **Total events**: 387 (2018–2024)
- **Commodities covered**: copper, corn, crude_oil_brent, crude_oil_wti, gold, natural_gas, silver, wheat
- **Train**: 180 events (2018-01-03 → 2021-12-15)
- **Calibration**: 68 events (2022-01-12 → 2022-12-20)
- **Test**: 139 events (2023-01-09 → 2024-12-18)

**Split logic:** train < 2022-01-01 · calibration 2022 · test ≥ 2023-01-01. LLM, calibration, and thresholds are fitted ONLY on train+calibration. All final metrics are on the hold-out test split — never seen before.

**Ground truth:**
- `expected_direction` — what an expert analyst would have predicted from the news text alone.
- `actual_direction_d{h}` — derived from real Yahoo Finance close price at d0 vs. d{h}, with |change| < 0.5% counted as neutral.

## 2. Headline metrics (test split, horizon = 7 trading days)

| Method | Accuracy vs. market | 95% CI | vs. label |
|---|---|---|---|
| baseline:random | 28.8% | [21.6%, 36.7%] | 30.2% |
| baseline:always_bullish | 47.5% | [39.6%, 55.4%] | 64.7% |
| baseline:keyword | 25.9% | [18.7%, 34.5%] | 41.0% |

> n = 139 evaluable events. CI is bootstrap-estimated over 1000 resamples. A baseline random-ternary classifier is 33%.

## 4. Confidence calibration

*(Calibration requires LLM predictions on both calibration and test splits. Run `python -m evaluation.walk_forward --split calibration` and `--split test` first.)*

## 5. Per-commodity accuracy (test split, d7)

| Commodity | LLM n | LLM acc | Keyword acc |
|---|---|---|---|
| copper | 0 | — | 15.4% |
| corn | 0 | — | 0.0% |
| crude_oil_brent | 0 | — | 57.9% |
| crude_oil_wti | 0 | — | 52.9% |
| gold | 0 | — | 20.4% |
| natural_gas | 0 | — | 0.0% |
| silver | 0 | — | 13.6% |
| wheat | 0 | — | 0.0% |

## 6. Multi-horizon accuracy (test split)

| Method | d1 | d3 | d7 | d14 | d30 |
|---|---|---|---|---|---|
| baseline:random | 29.5% | 28.8% | 28.8% | 33.8% | 30.2% |
| baseline:always_bullish | 30.9% | 37.4% | 47.5% | 48.2% | 54.7% |
| baseline:keyword | 34.5% | 33.8% | 25.9% | 30.2% | 31.7% |

## 7. Confusion matrix (LLM, test split)

## 8. P&L simulation (LLM, test split)

## 9. Honest limitations

- **Sample size**: 144 events total; ~60–70 on the test split. Power is limited — differences < ~10% accuracy points may not be statistically significant.
- **Hindsight in labels**: `expected_direction` was curated post-hoc. The **actual-market direction** is the objective truth used in all metrics and P&L.
- **Market-moving events bias**: the dataset is skewed toward *newsworthy* events — real-world news streams contain much more noise where the correct prediction is often neutral.
- **No cost modelling**: P&L is gross of transaction costs.
- **One news text per event**: production systems consume text continuously and can average multiple signals.

*Report generated: 2026-04-18T23:59:02*
