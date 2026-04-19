"""Download audio for the 11 curated historical YouTube videos + generate a
multi-commodity evaluation fixture.

For each URL:
  1. yt-dlp extracts audio -> WAV 16 kHz mono (Whisper-friendly)
  2. Derive expected commodities + directions from video title keywords
  3. Emit a new entry into historical_test_set.json

The produced fixture is consumed by `evaluation/run_multicommodity_eval.py`,
which runs the full pipeline on each audio file and measures per-video
commodity coverage + direction accuracy.

Usage:  python scripts/download_historical_audio.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio_samples" / "historical"
FIXTURE_PATH = ROOT / "evaluation" / "historical_test_set.json"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# Sync'd with SAVED_CATEGORIES 'historical' entries in src/dashboard/static/app.js
HISTORICAL_VIDEOS = [
    ("cnbc_tv18_oil_copper_127", "CNBC TV18: Oil + Copper record highs (1:27)",
     "https://www.youtube.com/watch?v=X_A08N9GO9g"),
    ("cnbc_tv18_gold_copper_126", "CNBC TV18: Gold $4k + Copper 3-mo high (1:26)",
     "https://www.youtube.com/watch?v=Ao6bO2CXm0E"),
    ("cnbc_tv18_oil_copper_gold_131", "CNBC TV18: Oil firm, Copper + Gold slip (1:31)",
     "https://www.youtube.com/watch?v=tziI68GYIj4"),
    ("cnbc_tv18_copper_crude_gold_134", "CNBC TV18: Copper record, Crude -2%, Gold gains (1:34)",
     "https://www.youtube.com/watch?v=9F30Dsb74l0"),
    ("cnbc_tv18_crude_gold_136", "CNBC TV18: Crude steady, Gold 2-mo low (1:36)",
     "https://www.youtube.com/watch?v=McyesJLRhGw"),
    ("gold_oil_rally_503", "Commodities rally: Gold + Oil (5:03)",
     "https://www.youtube.com/watch?v=eOmzQJn92rA"),
    ("gold_silver_copper_618", "Gold + Silver + Copper 2026 outlook (6:18)",
     "https://www.youtube.com/watch?v=Xmc83f-JOfU"),
    ("oil_gold_silver_copper_815", "Oil + Gold + Silver + Copper trade setups (8:15)",
     "https://www.youtube.com/watch?v=pU9Y3U0az9E"),
    ("cnbc_tv18_big_c_oils_metals_1056", "CNBC TV18 Big C: Oils + Metals outlook (10:56)",
     "https://www.youtube.com/watch?v=rS4KlK3BUh0"),
    ("cnbc_tv18_gold_silver_champions_1116", "CNBC TV18: Gold + Silver Commodity Champions (11:16)",
     "https://www.youtube.com/watch?v=FIGIJ__rIUI"),
    ("cnbc_tv18_gold_silver_copper_crude_1345",
     "CNBC TV18: Gold + Silver + Copper + Crude (13:45)",
     "https://www.youtube.com/watch?v=o0OMr9yerf4"),
]


# Commodity detection from title (all lowercase substring checks)
TITLE_COMMODITY_MAP = {
    "crude_oil_wti": ("crude", "oil", "wti", "opec"),
    "crude_oil_brent": ("brent",),
    "gold": ("gold",),
    "silver": ("silver",),
    "copper": ("copper",),
    "natural_gas": ("natural gas", "nat gas", "lng"),
    "wheat": ("wheat",),
    "corn": ("corn",),
}


def derive_expected_commodities(title: str) -> list[str]:
    """Build the expected-commodity list from a title's keywords."""
    low = title.lower()
    hits = []
    for canonical, keywords in TITLE_COMMODITY_MAP.items():
        if any(kw in low for kw in keywords):
            hits.append(canonical)
    # Dedup oil: if "crude/oil" triggers WTI but title mentions neither WTI nor Brent
    # specifically, include Brent too (most commentary discusses both)
    if "crude_oil_wti" in hits and "crude_oil_brent" not in hits:
        hits.append("crude_oil_brent")
    return sorted(set(hits))


# Direction hints — substrings in title that imply a direction per commodity.
# Order matters: checked in sequence, first match wins per commodity.
DIRECTION_HINTS = [
    (("record high", "gains", "rally", "boost", "surge", "higher", "record"),
     "bullish"),
    (("slip", "decline", "dip", "low", "drop", "fall", "bear"),
     "bearish"),
]


def derive_expected_directions(title: str, commodities: list[str]) -> dict[str, str]:
    """Best-effort direction per commodity from title keywords. Unknown -> neutral.

    NOT perfect — headlines are often ambiguous or describe multiple directions.
    Treated as a hint, not a strict ground truth.
    """
    low = title.lower()
    out: dict[str, str] = {}
    # Global title direction (if no commodity-specific hint)
    global_dir = "neutral"
    for keywords, direction in DIRECTION_HINTS:
        if any(kw in low for kw in keywords):
            global_dir = direction
            break
    # Per-commodity: scan for "<commodity_kw> <direction_kw>" patterns
    for com in commodities:
        com_kws = TITLE_COMMODITY_MAP.get(com, ())
        # Find segment near the commodity mention
        for kw in com_kws:
            idx = low.find(kw)
            if idx >= 0:
                # Look in a 40-char window after the commodity
                window = low[idx:idx + 40]
                for d_kws, d in DIRECTION_HINTS:
                    if any(dk in window for dk in d_kws):
                        out[com] = d
                        break
                if com in out:
                    break
        if com not in out:
            out[com] = global_dir
    return out


def download_audio(url: str, output_prefix: Path) -> Path | None:
    """Download bestaudio container (no ffmpeg post-processing needed).

    The pipeline's FileIngestor uses PyAV (libavformat), which decodes
    .webm / .m4a / .opus natively — no WAV conversion required.
    """
    # Check if any audio file with this prefix already exists
    for ext in (".webm", ".m4a", ".opus", ".mp3", ".wav"):
        candidate = output_prefix.with_suffix(ext)
        if candidate.exists():
            print(f"  [skip] already exists: {candidate.name}")
            return candidate
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "-f", "bestaudio",
        "-o", str(output_prefix.with_suffix(".%(ext)s")),
        url,
    ]
    try:
        result = subprocess.run(cmd, timeout=300, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  [FAIL] yt-dlp rc={result.returncode}: {result.stderr[:200]}")
            return None
        candidates = list(output_prefix.parent.glob(f"{output_prefix.name}.*"))
        for c in candidates:
            if c.suffix in (".webm", ".m4a", ".opus", ".mp3", ".wav"):
                return c
        return None
    except subprocess.TimeoutExpired:
        print("  [FAIL] download timeout (>300 s)")
        return None


def get_duration_seconds(audio_path: Path) -> float:
    """Read duration via PyAV (supports webm/m4a/opus/mp3/wav)."""
    try:
        import av
        container = av.open(str(audio_path))
        duration = float(container.duration) / 1_000_000.0 if container.duration else 0.0
        container.close()
        return duration
    except Exception:
        return 0.0


def main() -> None:
    fixture: list[dict] = []
    print(f"Downloading {len(HISTORICAL_VIDEOS)} historical videos -> {AUDIO_DIR}")

    for slug, title, url in HISTORICAL_VIDEOS:
        print(f"\n[{slug}]")
        print(f"  title: {title}")
        wav_path = download_audio(url, AUDIO_DIR / slug)
        if wav_path is None:
            print("  SKIPPED")
            continue
        duration = get_duration_seconds(wav_path)
        commodities = derive_expected_commodities(title)
        directions = derive_expected_directions(title, commodities)
        print(f"  [ok] {wav_path.name} ({duration:.1f}s) · commodities={commodities}")
        fixture.append({
            "video_id": slug,
            "title": title,
            "url": url,
            "audio_file": str(wav_path.relative_to(ROOT)).replace("\\", "/"),
            "duration_s": round(duration, 1),
            "expected_commodities": commodities,
            "expected_directions": directions,
            "notes": "Derived from title keywords; human-verified ground truth "
                     "requires listening to the audio.",
        })

    FIXTURE_PATH.write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\n[ok] Wrote {len(fixture)} entries to {FIXTURE_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
