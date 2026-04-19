from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.dashboard import server as dashboard_server
from src.dashboard.server import SignalBroadcaster, create_app, set_pipeline


@pytest.fixture
def client():
    broadcaster = SignalBroadcaster()
    app = create_app(broadcaster)
    return TestClient(app)


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Commodity Sentiment Monitor" in response.text


def test_stats_endpoint(client):
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert "chunks_processed" in data
    assert "total_signals" in data
    assert data["chunks_processed"] == 0


def test_signals_endpoint(client):
    response = client.get("/api/signals")
    assert response.status_code == 200
    assert response.json() == []


# ===== Pipeline live-apply settings endpoint =====

class _FakePipeline:
    """Minimal duck-typed stand-in for Pipeline used by /api/settings/pipeline."""
    def __init__(self):
        self._settings = SimpleNamespace(
            chunk_duration_s=10,
            whisper_model_size="small",
            whisper_language="en",
            anthropic_api_key="",
            openai_api_key="",
            llm_provider="anthropic",
        )
        self.calls: list[dict] = []

    async def set_runtime_settings(self, **kwargs):
        # Apply the values to _settings so /api/config reflects them
        self.calls.append(kwargs)
        if kwargs.get("chunk_duration_s") is not None:
            self._settings.chunk_duration_s = int(kwargs["chunk_duration_s"])
        if kwargs.get("whisper_model"):
            self._settings.whisper_model_size = kwargs["whisper_model"]
        if kwargs.get("whisper_language") is not None:
            self._settings.whisper_language = kwargs["whisper_language"]
        return {
            "ok": True,
            "applied": ["chunk_duration_s", "whisper_model", "whisper_language"],
            "pending": [],
            "notes": [],
            "active": {
                "chunk_duration_s": self._settings.chunk_duration_s,
                "whisper_model": self._settings.whisper_model_size,
                "whisper_language": self._settings.whisper_language,
            },
        }


@pytest.fixture
def pipeline_client():
    # Inject fake pipeline so /api/settings/pipeline has something to talk to
    broadcaster = SignalBroadcaster()
    app = create_app(broadcaster)
    fake = _FakePipeline()
    set_pipeline(fake)
    try:
        yield TestClient(app), fake
    finally:
        # Clear the ref so other tests don't see this fake
        dashboard_server._pipeline_ref = None


def test_pipeline_settings_live_apply(pipeline_client):
    client, fake = pipeline_client
    r = client.post(
        "/api/settings/pipeline",
        json={"chunk_duration_s": 8, "whisper_model": "base", "whisper_language": "cs"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert fake.calls == [
        {"chunk_duration_s": 8, "whisper_model": "base", "whisper_language": "cs"}
    ]
    assert data["active"]["chunk_duration_s"] == 8
    assert data["active"]["whisper_model"] == "base"
    assert data["active"]["whisper_language"] == "cs"

    # /api/config should reflect the new values (read from _settings, not env)
    cfg = client.get("/api/config").json()
    assert cfg["chunk_duration_s"] == 8
    assert cfg["whisper_model"] == "base"
    assert cfg["whisper_language"] == "cs"


@pytest.mark.parametrize(
    ("payload", "expected_error_snippet"),
    [
        ({"chunk_duration_s": 0}, "5-15"),
        ({"chunk_duration_s": 50}, "5-15"),
        ({"chunk_duration_s": "abc"}, "integer"),
        ({"whisper_model": "xxl"}, "whisper_model must be one of"),
    ],
)
def test_pipeline_settings_validation(pipeline_client, payload, expected_error_snippet):
    client, _fake = pipeline_client
    r = client.post("/api/settings/pipeline", json=payload)
    # Endpoint returns 200 with ok=False for validation errors (matches
    # existing /api/settings/api-key style)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert expected_error_snippet in data["error"]


def test_pipeline_settings_no_pipeline(client):
    # When no pipeline is injected, endpoint reports unavailable cleanly
    dashboard_server._pipeline_ref = None
    r = client.post("/api/settings/pipeline", json={"whisper_model": "small"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


# ===== Multi-source pipeline endpoints =====

class _FakeMultiSourcePipeline:
    """Fake Pipeline exposing the new multi-source API."""
    def __init__(self):
        self._settings = SimpleNamespace(
            chunk_duration_s=10,
            whisper_model_size="small",
            whisper_language="en",
            input_file="",
            stream_url="",
        )
        self._running = False
        self._sources: dict = {}
        self.add_calls: list[str] = []
        self.remove_calls: list[str] = []
        self.stop_called = False

    async def add_source(self, url: str):
        self.add_calls.append(url)
        if url in self._sources:
            return {"ok": True, "started": False, "reason": "already active"}
        self._sources[url] = object()
        self._running = True
        return {"ok": True, "started": True, "reason": "launched"}

    async def remove_source(self, url: str):
        self.remove_calls.append(url)
        if url not in self._sources:
            return {"ok": False, "reason": "not active"}
        del self._sources[url]
        if not self._sources:
            self._running = False
        return {"ok": True}

    def active_sources(self):
        return list(self._sources.keys())

    def stop(self):
        self.stop_called = True
        self._sources.clear()
        self._running = False

    async def wait_stopped(self, timeout: float = 10.0):
        return True


@pytest.fixture
def multisource_client():
    broadcaster = SignalBroadcaster()
    app = create_app(broadcaster)
    fake = _FakeMultiSourcePipeline()
    set_pipeline(fake)
    try:
        yield TestClient(app), fake
    finally:
        dashboard_server._pipeline_ref = None


def test_pipeline_start_adds_source(multisource_client):
    client, fake = multisource_client
    r = client.post("/api/pipeline/start", json={"source": "https://example.com/stream1"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["started"] is True
    assert fake.add_calls == ["https://example.com/stream1"]


def test_pipeline_start_multiple_sources_concurrent(multisource_client):
    """Adding a second source returns ok=True — no 'already running' error.

    This is the regression fix: previously the pipeline errored out with
    'pipeline already running' when a user tried to add a second stream.
    """
    client, fake = multisource_client
    urls = [
        "https://www.youtube.com/watch?v=X_A08N9GO9g",
        "https://www.youtube.com/watch?v=Ao6bO2CXm0E",
        "https://www.bloomberg.com/live",
    ]
    for url in urls:
        r = client.post("/api/pipeline/start", json={"source": url})
        assert r.status_code == 200
        assert r.json()["ok"] is True
    assert fake.active_sources() == urls
    status = client.get("/api/pipeline/status").json()
    assert set(status["sources"]) == set(urls)
    assert status["running"] is True


def test_pipeline_stop_single_source(multisource_client):
    """POST /api/pipeline/stop with a source URL stops only that one."""
    client, fake = multisource_client
    # Add 2 sources
    client.post("/api/pipeline/start", json={"source": "url-A"})
    client.post("/api/pipeline/start", json={"source": "url-B"})
    # Remove only url-A
    r = client.post("/api/pipeline/stop", json={"source": "url-A"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["scope"] == "source"
    assert fake.remove_calls == ["url-A"]
    # url-B should still be active
    assert fake.active_sources() == ["url-B"]
    assert fake.stop_called is False


def test_pipeline_stop_all(multisource_client):
    """POST /api/pipeline/stop without a source stops everything."""
    client, fake = multisource_client
    client.post("/api/pipeline/start", json={"source": "url-A"})
    client.post("/api/pipeline/start", json={"source": "url-B"})
    r = client.post("/api/pipeline/stop", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["scope"] == "all"
    assert fake.stop_called is True
    assert fake.active_sources() == []


def test_pipeline_start_duplicate_source_is_noop(multisource_client):
    client, fake = multisource_client
    client.post("/api/pipeline/start", json={"source": "url-A"})
    r = client.post("/api/pipeline/start", json={"source": "url-A"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["started"] is False
    # add_source was called twice but only one source is active
    assert fake.active_sources() == ["url-A"]
