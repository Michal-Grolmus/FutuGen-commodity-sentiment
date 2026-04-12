"""Tests for CLI argument parsing."""
from __future__ import annotations

from unittest.mock import patch

from src.main import parse_args


def test_help_flag():
    """CLI --help should work without error."""
    with patch("sys.argv", ["main.py", "--help"]):
        try:
            parse_args()
        except SystemExit as e:
            assert e.code == 0


def test_input_file_arg():
    with patch("sys.argv", ["main.py", "--input-file", "test.wav"]):
        args = parse_args()
        assert args.input_file == "test.wav"


def test_short_flags():
    with patch("sys.argv", ["main.py", "-f", "test.wav", "-p", "9000", "-w", "tiny"]):
        args = parse_args()
        assert args.input_file == "test.wav"
        assert args.port == 9000
        assert args.whisper_model == "tiny"


def test_stream_url_arg():
    with patch("sys.argv", ["main.py", "--stream-url", "https://youtube.com/watch?v=abc"]):
        args = parse_args()
        assert args.stream_url == "https://youtube.com/watch?v=abc"


def test_defaults():
    with patch("sys.argv", ["main.py"]):
        args = parse_args()
        assert args.input_file is None
        assert args.stream_url is None
        assert args.port is None
        assert args.whisper_model is None
        assert args.chunk_duration is None
