"""Tests for stream URL validation (security)."""
from __future__ import annotations

import pytest

from src.ingestion.stream_ingestor import StreamIngestor


def test_valid_https_url():
    """HTTPS URLs should be accepted."""
    ingestor = StreamIngestor("https://www.youtube.com/watch?v=test123")
    assert ingestor._url == "https://www.youtube.com/watch?v=test123"


def test_valid_rtmp_url():
    """RTMP URLs should be accepted."""
    ingestor = StreamIngestor("rtmp://stream.example.com/live")
    assert ingestor._url == "rtmp://stream.example.com/live"


def test_reject_file_url():
    """file:// URLs should be rejected (path traversal risk)."""
    with pytest.raises(ValueError, match="Invalid stream URL"):
        StreamIngestor("file:///etc/passwd")


def test_reject_empty_host():
    """URLs without hostname should be rejected."""
    with pytest.raises(ValueError, match="valid hostname"):
        StreamIngestor("https://")


def test_reject_ftp_url():
    """FTP URLs should be rejected."""
    with pytest.raises(ValueError, match="Invalid stream URL"):
        StreamIngestor("ftp://example.com/stream")
