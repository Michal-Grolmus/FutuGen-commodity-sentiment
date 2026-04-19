"""Append-only JSONL log of aggregated segments.

Each segment is written once on close (plus optionally updated when
reality_score lands). Pre-close in-flight segments live in aggregator memory only.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from src.models import Segment

logger = logging.getLogger(__name__)

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "segments_log.jsonl"

_lock = threading.Lock()


def _ensure_dir() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def append(segment: Segment) -> None:
    """Write a closed segment to the log."""
    _ensure_dir()
    entry = segment.model_dump(mode="json")
    with _lock, open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.debug("Logged segment %s (commodity=%s, %d chunks)",
                 segment.segment_id, segment.primary_commodity,
                 len(segment.chunk_ids))


def update_reality_score(segment_id: str, reality_score: dict[str, Any]) -> bool:
    """Rewrite the log with reality_score filled in for a specific segment."""
    _ensure_dir()
    if not LOG_PATH.exists():
        return False
    updated = False
    with _lock:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
        new_lines: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                new_lines.append(line)
                continue
            if entry.get("segment_id") == segment_id:
                entry["reality_score"] = reality_score
                updated = True
            new_lines.append(json.dumps(entry, ensure_ascii=False))
        if updated:
            LOG_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updated


def read_all() -> list[dict[str, Any]]:
    _ensure_dir()
    if not LOG_PATH.exists():
        return []
    entries: list[dict[str, Any]] = []
    with _lock, open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def compute_stats() -> dict[str, Any]:
    """Aggregate segment accuracy per commodity / per stream."""
    entries = read_all()
    total = len(entries)
    by_commodity: dict[str, dict[str, Any]] = {}
    by_stream: dict[str, dict[str, Any]] = {}

    horizons = ["h1m", "h5m", "h15m", "h1h"]

    def _bucket(d: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
        if key not in d:
            d[key] = {"total": 0, "with_reality": 0, "correct": {h: 0 for h in horizons}}
        return d[key]

    for e in entries:
        com = e.get("primary_commodity", "unknown")
        stream = e.get("stream_id", "unknown")
        rs = e.get("reality_score") or {}

        for bucket in (_bucket(by_commodity, com), _bucket(by_stream, stream)):
            bucket["total"] += 1
            if rs:
                bucket["with_reality"] += 1
                for h in horizons:
                    if rs.get(f"correct_{h}") is True:
                        bucket["correct"][h] += 1

    # Compute accuracy per horizon
    for buckets in (by_commodity, by_stream):
        for _key, bucket in buckets.items():
            bucket["accuracy"] = {}
            n = bucket["with_reality"]
            for h in horizons:
                bucket["accuracy"][h] = (bucket["correct"][h] / n) if n > 0 else None

    return {
        "total_segments": total,
        "by_commodity": by_commodity,
        "by_stream": by_stream,
    }
