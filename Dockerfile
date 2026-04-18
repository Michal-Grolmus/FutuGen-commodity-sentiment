FROM python:3.12-slim

# ffmpeg needed for live stream ingestion (yt-dlp pipes to ffmpeg)
# File ingestion uses PyAV (Python package) so no ffmpeg needed for demos
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

WORKDIR /app

# Install deps first (better layer caching)
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# Copy the rest
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

CMD ["python", "-m", "src.main"]
