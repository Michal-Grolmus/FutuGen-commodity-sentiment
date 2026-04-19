FROM python:3.12-slim

# File and stream ingestion both run on PyAV (bundled libavformat), so no
# external ffmpeg binary is required — `pip install av` ships a working
# decoder. StreamIngestor auto-detects ffmpeg on PATH and uses the faster
# subprocess path when present; otherwise it falls back to PyAV seamlessly.
# To opt into the ffmpeg backend, uncomment the apt line below (+80 MB image).
# RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
#     && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

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
