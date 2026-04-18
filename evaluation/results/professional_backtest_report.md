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

## 9. Horizon analysis — is the clock wrong, not the direction?

*Source: baseline:keyword (LLM predictions not available)*

Different event types react on different timescales — a supply shock spikes + reverts in days, a Fed pivot takes weeks to price in. Fixed-d7 evaluation can under-count predictions that were directionally correct but evaluated at the wrong clock.

### Upper / lower bounds on hit rate

- **Any-horizon hit rate** (correct at d1 OR d3 OR d7 OR d14 OR d30): **73.4%** — loose upper bound.
- **All-horizons hit rate** (correct at every horizon — durable signal): **4.3%** — tight lower bound.
- Gap between them = predictions whose direction was right but *timing-dependent*. Large gap → pick better horizon; small gap → signal is stable or universally wrong.

### Signal persistence P(correct at d_h | correct at d1)

| Horizon | Still correct |
|---|---|
| d1 | 100.0% |
| d3 | 54.2% |
| d7 | 33.3% |
| d14 | 27.1% |
| d30 | 29.2% |

> ~1.0 = durable; 0.5 = the signal is already half reverted by that horizon; <0.5 = trade flipped against you.

### Time-to-peak distribution

- Mean peak horizon: **d16.5** (71 directional trades).
- Distribution: d1: 6 | d3: 10 | d7: 14 | d14: 12 | d30: 29

### Maximum Favorable / Adverse Excursion

- **Avg MFE** (best the average trade got to): **+5.04%**
- **Avg MAE** (worst the average trade dropped to): **-3.25%**
- **MFE/|MAE|** ratio: **1.55** — > 1.5 indicates asymmetric payoff (good); < 1 means average drawdown exceeds average upside.

### Optimal horizon per event type *(learned on train+cal)*

| Event type | Best horizon | Accuracy | n (train+cal) |
|---|---|---|---|
| monetary | d7 | 38.1% | 21 |
| macro | d1 | 23.1% | 13 |
| geopolitical | d3 | 69.2% | 13 |
| opec | d1 | 33.3% | 9 |
| supply_disruption | d1 | 60.0% | 5 |
| trade_policy | d1 | 33.3% | 3 |
| weather | d7 | 50.0% | 2 |
| market_structure | d7 | 100.0% | 1 |
| financial_crisis | d1 | 0.0% | 1 |

### Adaptive horizon vs. fixed d=7 (test split)

- **Fixed d=7 accuracy**: 25.9%
- **Adaptive (per-type horizon learned on train+cal)**: 32.4%
- **Uplift**: +6.5% → *adaptive wins*

> A positive uplift means **failing predictions at d=7 were often correct at another horizon matching their event type**. A zero or negative uplift means fixed-d7 is already close to optimal.

## 10. Honest limitations

- **Sample size**: 387 events total; ~140 on the test split. Power is limited — differences < ~8% accuracy points may not be statistically significant.
- **Hindsight in labels**: `expected_direction` was curated post-hoc. The **actual-market direction** is the objective truth used in all metrics and P&L.
- **Market-moving events bias**: the dataset is skewed toward *newsworthy* events — real-world news streams contain much more noise where the correct prediction is often neutral.
- **No cost modelling**: P&L is gross of transaction costs.
- **One news text per event**: production systems consume text continuously and can average multiple signals.

*Report generated: 2026-04-19T00:07:15*
