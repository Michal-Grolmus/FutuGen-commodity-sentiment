"""Generate TTS audio samples from the evaluation test set using edge-tts."""
from __future__ import annotations

import asyncio
import io
import json
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_SET = ROOT / "evaluation" / "test_set.json"
SAMPLES_DIR = ROOT / "audio_samples"

TARGET_RATE = 16_000


async def generate_one(text: str, output_wav: Path) -> None:
    """Generate audio with edge-tts, decode MP3 to WAV using av (PyAV)."""
    import av
    import edge_tts

    # Generate MP3 bytes in memory
    communicate = edge_tts.Communicate(text, voice="en-US-GuyNeural")
    mp3_bytes = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_bytes += chunk["data"]

    # Decode MP3 -> raw PCM using PyAV (no ffmpeg binary needed)
    container = av.open(io.BytesIO(mp3_bytes), format="mp3")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_RATE)

    pcm_data = b""
    for frame in container.decode(audio=0):
        resampled = resampler.resample(frame)
        for r in resampled:
            pcm_data += bytes(r.planes[0])

    container.close()

    # Write WAV
    with wave.open(str(output_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TARGET_RATE)
        wf.writeframes(pcm_data)

    duration = len(pcm_data) / (TARGET_RATE * 2)
    print(f"  Generated: {output_wav.name} ({duration:.1f}s)")


async def main() -> None:
    SAMPLES_DIR.mkdir(exist_ok=True)

    with open(TEST_SET, encoding="utf-8") as f:
        test_set = json.load(f)

    print(f"Generating {len(test_set)} audio samples...")

    for item in test_set:
        wav_name = Path(item["audio_file"]).name
        wav_path = SAMPLES_DIR / wav_name

        if wav_path.exists():
            print(f"  Skipping (exists): {wav_name}")
            continue

        await generate_one(item["transcript_text"], wav_path)

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
