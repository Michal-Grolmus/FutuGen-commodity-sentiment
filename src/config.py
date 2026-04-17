from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model_extraction: str = "claude-haiku-4-5-20251001"
    anthropic_model_scoring: str = "claude-haiku-4-5-20251001"

    # Whisper
    whisper_model_size: str = "small"  # small = best quality/speed tradeoff on CPU
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str = "en"  # force English; empty string = auto-detect

    # Ingestion
    chunk_duration_s: int = 10
    stream_url: str = ""
    input_file: str = ""

    # Pipeline
    max_queue_size: int = 50
    pipeline_timeout_s: int = 1800

    # Dashboard
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000

    # Bonus: prices
    enable_price_tracking: bool = True  # RAG: enrich scoring with live commodity prices

    # Bonus: notifications
    slack_webhook_url: str = ""
    notification_confidence_threshold: float = 0.8

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
