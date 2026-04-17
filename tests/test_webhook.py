"""Tests for Slack notification webhook."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.models import CommoditySignal, Direction, Timeframe
from src.notifications.webhook import SlackNotifier


def _make_signal(confidence: float = 0.9) -> CommoditySignal:
    return CommoditySignal(
        commodity="crude_oil_wti",
        display_name="WTI Crude Oil",
        direction=Direction.BULLISH,
        confidence=confidence,
        rationale="Production cut reduces supply.",
        timeframe=Timeframe.SHORT_TERM,
        source_text="OPEC cut production",
    )


@pytest.mark.asyncio
async def test_notifies_high_confidence():
    """Should send notification when confidence > threshold."""
    notifier = SlackNotifier("https://hooks.slack.com/test", threshold=0.8)
    with patch.object(notifier, "_client") as mock_client:
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = lambda: None
        mock_client.post = AsyncMock(return_value=mock_resp)
        await notifier.notify_if_high_confidence(_make_signal(0.9))
        mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_skips_low_confidence():
    """Should NOT send notification when confidence < threshold."""
    notifier = SlackNotifier("https://hooks.slack.com/test", threshold=0.8)
    with patch.object(notifier, "_client") as mock_client:
        mock_client.post = AsyncMock()
        await notifier.notify_if_high_confidence(_make_signal(0.5))
        mock_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_skips_empty_url():
    """Should NOT send notification when webhook URL is empty."""
    notifier = SlackNotifier("", threshold=0.8)
    with patch.object(notifier, "_client") as mock_client:
        mock_client.post = AsyncMock()
        await notifier.notify_if_high_confidence(_make_signal(0.95))
        mock_client.post.assert_not_called()
