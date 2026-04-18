"""Train / calibration / test splits for the historical dataset.

Split by DATE (point-in-time, no leakage):
  - train       — prompt design + few-shot curation (never used for final metrics)
  - calibration — fit confidence calibration curve
  - test        — hold-out, final honest metrics

Default split:
  train       < 2022-01-01
  calibration   2022-01-01 .. 2022-12-31
  test        >= 2023-01-01

Rationale: gives ~3 years train (macro cycle), 1 year calibration, 2 years test
(bull 2023 + recession scare 2024) — covers multiple regimes on both sides.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SplitConfig:
    train_end: str = "2022-01-01"       # exclusive
    calibration_end: str = "2023-01-01"  # exclusive


def split_events(
    events: list[dict],
    config: SplitConfig | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Partition events into (train, calibration, test) by date."""
    cfg = config or SplitConfig()
    train, calib, test = [], [], []
    for ev in events:
        d = ev["date"]
        if d < cfg.train_end:
            train.append(ev)
        elif d < cfg.calibration_end:
            calib.append(ev)
        else:
            test.append(ev)
    return train, calib, test


def describe_split(
    train: list[dict],
    calib: list[dict],
    test: list[dict],
) -> dict[str, object]:
    """Summary stats for reporting."""
    def stats(events: list[dict]) -> dict[str, object]:
        if not events:
            return {"count": 0}
        dates = sorted(e["date"] for e in events)
        return {
            "count": len(events),
            "date_min": dates[0],
            "date_max": dates[-1],
        }

    return {
        "train": stats(train),
        "calibration": stats(calib),
        "test": stats(test),
    }
