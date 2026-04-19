# Multi-commodity evaluation report

*Generated: 2026-04-19T19:46:21+00:00*

## Setup

- Fixture: `evaluation\historical_test_set.json`
- Videos evaluated: 5
- Pipeline: file ingestion -> Whisper -> Claude Haiku 4.5 extraction + scoring -> segment aggregation
- Ground truth: derived from video title keywords (commodity list + direction hints). Not manually verified, so direction accuracy is a rough estimate.

## Aggregate metrics

- **Mean commodity recall**: 20.0%
- **Mean direction accuracy** (on matched commodities): 0.0%
- **Total signals**: 10
- **Total segments**: 7
- **Total cost**: $0.0243
- **Total audio duration**: 454s (7.6 min)
- **Total wall-clock processing**: 178s (0.39× real-time)

## Per-video results

### cnbc_tv18_oil_copper_127
- **Title**: CNBC TV18: Oil + Copper record highs (1:27)
- **URL**: https://www.youtube.com/watch?v=X_A08N9GO9g
- **Duration**: 86.9s, wall-clock 22.0s (11 chunks)
- **Expected commodities**: copper, crude_oil_brent, crude_oil_wti
- **Detected commodities**: (none)
- **Missed** (expected but not detected): copper, crude_oil_brent, crude_oil_wti
- **Commodity recall**: 0.0%
- **Signals**: 0 · **Segments**: 0 · **Cost**: $0.0010

### cnbc_tv18_gold_copper_126
- **Title**: CNBC TV18: Gold $4k + Copper 3-mo high (1:26)
- **URL**: https://www.youtube.com/watch?v=Ao6bO2CXm0E
- **Duration**: 86.2s, wall-clock 21.1s (11 chunks)
- **Expected commodities**: copper, gold
- **Detected commodities**: (none)
- **Missed** (expected but not detected): copper, gold
- **Commodity recall**: 0.0%
- **Signals**: 0 · **Segments**: 0 · **Cost**: $0.0000

### cnbc_tv18_oil_copper_gold_131
- **Title**: CNBC TV18: Oil firm, Copper + Gold slip (1:31)
- **URL**: https://www.youtube.com/watch?v=tziI68GYIj4
- **Duration**: 90.7s, wall-clock 69.8s (11 chunks)
- **Expected commodities**: copper, crude_oil_brent, crude_oil_wti, gold
- **Detected commodities**: copper, crude_oil_brent, crude_oil_wti, gold, lead, nickel, silver
- **Matched**: copper, crude_oil_brent, crude_oil_wti, gold
- **Extra** (detected but not in expected set): lead, nickel, silver
- **Commodity recall**: 100.0%
- **Direction accuracy**: 0.0%
- **Direction detail**:
  - [miss] copper: expected=bearish, detected=bullish (conf 0.75)
  - [miss] crude_oil_brent: expected=bearish, detected=neutral (conf 0.65)
  - [miss] crude_oil_wti: expected=bearish, detected=neutral (conf 0.65)
  - [miss] gold: expected=bearish, detected=bullish (conf 0.75)
- **Signals**: 10 · **Segments**: 7 · **Cost**: $0.0215

### cnbc_tv18_copper_crude_gold_134
- **Title**: CNBC TV18: Copper record, Crude -2%, Gold gains (1:34)
- **URL**: https://www.youtube.com/watch?v=9F30Dsb74l0
- **Duration**: 93.9s, wall-clock 53.1s (12 chunks)
- **Expected commodities**: copper, crude_oil_brent, crude_oil_wti, gold
- **Detected commodities**: (none)
- **Missed** (expected but not detected): copper, crude_oil_brent, crude_oil_wti, gold
- **Commodity recall**: 0.0%
- **Signals**: 0 · **Segments**: 0 · **Cost**: $0.0018

### cnbc_tv18_crude_gold_136
- **Title**: CNBC TV18: Crude steady, Gold 2-mo low (1:36)
- **URL**: https://www.youtube.com/watch?v=McyesJLRhGw
- **Duration**: 96.0s, wall-clock 12.1s (12 chunks)
- **Expected commodities**: crude_oil_brent, crude_oil_wti, gold
- **Detected commodities**: (none)
- **Missed** (expected but not detected): crude_oil_brent, crude_oil_wti, gold
- **Commodity recall**: 0.0%
- **Signals**: 0 · **Segments**: 0 · **Cost**: $0.0000

## Caveats

- **Ground truth from titles**: the `expected_commodities` and `expected_directions` are derived from video title keywords. Many videos discuss additional commodities not in the title — those appear as *Extra*, which is not necessarily an error.
- **Direction accuracy** uses the highest-confidence signal per commodity across the whole video. A segment-level breakdown would be more precise but requires manual per-segment labeling.
- **Whisper STT errors** (misheard commodity names, cut-off words at chunk boundaries) reduce recall, especially for short commodities like 'corn' that sound like common words.

