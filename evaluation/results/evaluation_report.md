# Evaluation Report

## Summary

- **Total excerpts**: 12
- **Direction accuracy**: 100.0%
- **Avg commodity recall**: 100.0%

## Confusion Matrix

| Actual \ Predicted | bullish | bearish | neutral |
|---|---|---|---|
| **bullish** | 8 | 0 | 0 |
| **bearish** | 0 | 2 | 0 |
| **neutral** | 0 | 0 | 2 |

## Error Analysis

No errors.

## Improvement Suggestions

- Add more context via RAG (historical price data, recent news) to improve scoring accuracy
- Use few-shot examples in prompts for ambiguous cases (mixed signals, neutral)
- Implement confidence calibration using temperature scaling
- Add multi-turn analysis for complex scenarios with competing signals
