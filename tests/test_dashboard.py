from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.dashboard.server import SignalBroadcaster, create_app


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
