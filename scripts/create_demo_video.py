"""Generate a narrated demo video (MP4) for the Commodity Sentiment Monitor.

Creates title slides with voice narration using edge-tts + Pillow + PyAV.
Output: demo_video.mp4 (max 5 min as per assignment)
"""
from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

import av
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo_video.mp4"

WIDTH, HEIGHT = 1280, 720
FPS = 1  # slideshow-style: 1 frame per second
BG = (15, 17, 23)  # dark background matching dashboard
BLUE = (88, 166, 255)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)
WHITE = (225, 228, 232)
GRAY = (139, 148, 158)

# Narration script: (slide_text_lines, narration_text, duration_seconds)
SLIDES = [
    # Intro (15s)
    (
        ["Commodity Sentiment Monitor", "", "Real-time commodity impact analysis", "from live audio streams"],
        "Welcome to the Commodity Sentiment Monitor demo. This system processes live audio streams, "
        "transcribes speech in real time, extracts commodity-relevant entities, and scores their "
        "probable market impact.",
        12,
    ),
    # Architecture (15s)
    (
        ["Architecture: 3-Layer Pipeline", "",
         "1. Ingestion  — ffmpeg + yt-dlp → audio chunks",
         "2. STT        — faster-whisper → transcript",
         "3. Analysis    — Claude API → signals",
         "", "All connected by async queues"],
        "The architecture has three layers connected by async queues. "
        "First, the ingestion layer captures audio from live streams or files and segments it into chunks. "
        "Second, faster-whisper transcribes each chunk with word-level timestamps. "
        "Third, Claude Haiku extracts commodity entities and scores their market impact.",
        15,
    ),
    # Dashboard (10s)
    (
        ["Dashboard Features", "",
         "• Live signals with bullish/bearish cards",
         "• Sentiment summary bar",
         "• Confidence heatmap (8 commodities)",
         "• 30-day commodity price charts",
         "• Pipeline latency monitor"],
        "The web dashboard shows results in real time. It includes live signal cards, "
        "a sentiment summary bar, a confidence heatmap for eight commodities, "
        "thirty-day price sparkline charts from Yahoo Finance, and a latency monitor.",
        10,
    ),
    # Demo mode (10s)
    (
        ["Demo Mode (No API Key Needed)", "",
         "Start the app → Click 'Start Demo'",
         "→ 12 evaluation scenarios replay live",
         "", "OPEC cuts, Fed decisions, sanctions,",
         "drought, mining strikes, geopolitics..."],
        "The app includes a built-in demo mode. Without any API key, the recruiter can click "
        "Start Demo and watch twelve real evaluation scenarios replay as live signals. "
        "This covers OPEC production cuts, Federal Reserve decisions, sanctions, weather events, "
        "and geopolitical tensions.",
        12,
    ),
    # Evaluation results (15s)
    (
        ["Evaluation Results", "",
         "Direction accuracy:  100% (12/12)",
         "Commodity recall:    100%",
         "",
         "Confusion Matrix:",
         "  Bullish: 8 correct",
         "  Bearish: 2 correct",
         "  Neutral: 2 correct"],
        "The evaluation framework tested all twelve scenarios using Claude as the analysis engine. "
        "Direction accuracy was one hundred percent — all twelve predictions matched ground truth. "
        "The confusion matrix shows eight bullish, two bearish, and two neutral, all classified correctly.",
        12,
    ),
    # Real-world testing (10s)
    (
        ["Real-World Audio Testing", "",
         "Tested on YouTube videos:",
         "• Bloomberg OPEC coverage — 7/7 keywords (100%)",
         "• Fed/Gold analysis      — 5/5 keywords (100%)",
         "",
         "STT latency: 0.2x real-time",
         "(15x faster than required)"],
        "The system was tested on real Bloomberg and financial analyst audio from YouTube. "
        "Keyword detection was one hundred percent on professional broadcast audio. "
        "Speech-to-text latency averaged zero point two x real-time, "
        "which is fifteen times faster than the three x requirement.",
        12,
    ),
    # Tech stack (10s)
    (
        ["Technology Stack", "",
         "STT:        faster-whisper (local, free)",
         "NLP:        Claude Haiku 4.5 (few-shot, RAG)",
         "Dashboard:  FastAPI + SSE + vanilla JS",
         "Testing:    52 tests, mypy, ruff",
         "Deploy:     Docker + docker-compose",
         "",
         "Total API cost: ~$2.35 (budget: $10)"],
        "The tech stack uses faster-whisper for free local transcription, "
        "Claude Haiku for entity extraction with few-shot prompting and RAG context from Yahoo Finance. "
        "The dashboard uses FastAPI with server-sent events. "
        "The project has fifty-two tests, zero mypy errors, and full Docker support. "
        "Total estimated API cost is two dollars and thirty-five cents, well under the ten dollar budget.",
        15,
    ),
    # Closing (8s)
    (
        ["Commodity Sentiment Monitor", "",
         "github.com/[repo]", "",
         "52 tests • 100% accuracy • 0.2x latency",
         "Docker ready • RAG • Backtesting",
         "",
         "Built with Claude (Anthropic)"],
        "Thank you for watching. The complete source code, documentation, and evaluation report "
        "are available in the GitHub repository. The system is ready for production use.",
        8,
    ),
]


def make_frame(lines: list[str], width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    """Create a slide frame with text."""
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    # Use default font (no system font dependency)
    try:
        title_font = ImageFont.truetype("arial.ttf", 36)
        body_font = ImageFont.truetype("arial.ttf", 24)
    except OSError:
        title_font = ImageFont.load_default()
        body_font = ImageFont.load_default()

    y = 120
    for i, line in enumerate(lines):
        if not line:
            y += 30
            continue
        font = title_font if i == 0 else body_font
        color = BLUE if i == 0 else WHITE
        if line.startswith("•"):
            color = GREEN
        if "100%" in line or "correct" in line.lower():
            color = GREEN
        if "$" in line:
            color = YELLOW

        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2 if i == 0 else 140
        draw.text((x, y), line, fill=color, font=font)
        y += 50 if i == 0 else 40

    return img


async def generate_narration(text: str, output_path: Path) -> None:
    """Generate WAV narration using edge-tts."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice="en-US-GuyNeural")
    mp3_bytes = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_bytes += chunk["data"]

    # Decode MP3 to WAV using PyAV
    container = av.open(io.BytesIO(mp3_bytes), format="mp3")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=44100)
    pcm = b""
    for frame in container.decode(audio=0):
        for r in resampler.resample(frame):
            pcm += bytes(r.planes[0])
    container.close()

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(pcm)


async def main() -> None:
    print("Generating demo video...")

    # Generate narration for each slide
    audio_dir = ROOT / "demo_frames"
    audio_dir.mkdir(exist_ok=True)

    all_audio = b""
    frames_with_duration: list[tuple[Image.Image, float]] = []

    for i, (lines, narration, min_duration) in enumerate(SLIDES):
        print(f"  Slide {i + 1}/{len(SLIDES)}: {lines[0]}")

        # Generate narration audio
        audio_path = audio_dir / f"narration_{i:02d}.wav"
        if not audio_path.exists():
            await generate_narration(narration, audio_path)

        # Get audio duration
        with wave.open(str(audio_path), "rb") as wf:
            audio_duration = wf.getnframes() / wf.getframerate()
            audio_bytes = wf.readframes(wf.getnframes())

        duration = max(min_duration, audio_duration + 1)
        all_audio += audio_bytes

        # Pad silence if slide duration > audio duration
        silence_samples = int((duration - audio_duration) * 44100) * 2  # 16-bit mono
        all_audio += b"\x00" * max(0, silence_samples)

        frame = make_frame(lines)
        frames_with_duration.append((frame, duration))

    # Write combined audio
    combined_audio_path = audio_dir / "combined.wav"
    with wave.open(str(combined_audio_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(all_audio)

    # Create MP4 with PyAV
    print("  Encoding MP4...")
    output = av.open(str(OUT), mode="w")
    video_stream = output.add_stream("libx264", rate=FPS)
    video_stream.width = WIDTH
    video_stream.height = HEIGHT
    video_stream.pix_fmt = "yuv420p"

    # Add audio stream
    audio_stream = output.add_stream("aac", rate=44100)
    audio_stream.layout = "mono"

    # Write video frames
    pts = 0
    for img, duration in frames_with_duration:
        rgb_frame = av.VideoFrame.from_image(img)
        yuv_frame = rgb_frame.reformat(format="yuv420p")
        for _ in range(int(duration)):
            yuv_frame.pts = pts
            pts += 1
            for packet in video_stream.encode(yuv_frame):
                output.mux(packet)

    # Flush video
    for packet in video_stream.encode():
        output.mux(packet)

    # Write audio
    audio_container = av.open(str(combined_audio_path))
    for frame in audio_container.decode(audio=0):
        frame.pts = None
        for packet in audio_stream.encode(frame):
            output.mux(packet)
    audio_container.close()

    for packet in audio_stream.encode():
        output.mux(packet)

    output.close()

    total_duration = sum(d for _, d in frames_with_duration)
    print(f"\nDone! Video saved: {OUT}")
    print(f"Duration: {total_duration:.0f}s ({total_duration / 60:.1f} min)")
    print(f"Size: {OUT.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    asyncio.run(main())
