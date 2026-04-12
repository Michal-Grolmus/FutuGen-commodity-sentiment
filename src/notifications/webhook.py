from __future__ import annotations

import logging

import httpx

from src.models import CommoditySignal

logger = logging.getLogger(__name__)


class SlackNotifier:
    def __init__(self, webhook_url: str, threshold: float = 0.8) -> None:
        self._webhook_url = webhook_url
        self._threshold = threshold
        self._client = httpx.AsyncClient(timeout=10)

    async def notify_if_high_confidence(self, signal: CommoditySignal) -> None:
        if signal.confidence < self._threshold:
            return

        if not self._webhook_url:
            return

        emoji = {
            "bullish": ":chart_with_upwards_trend:",
            "bearish": ":chart_with_downwards_trend:",
            "neutral": ":left_right_arrow:",
        }
        direction_emoji = emoji.get(signal.direction.value, "")

        payload = {
            "text": (
                f"{direction_emoji} *{signal.display_name}* — {signal.direction.value.upper()}\n"
                f"Confidence: {signal.confidence:.0%} | Timeframe: {signal.timeframe.value.replace('_', ' ')}\n"
                f">{signal.rationale}"
            ),
        }

        try:
            resp = await self._client.post(self._webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Slack notification sent for %s", signal.commodity)
        except Exception:
            logger.exception("Failed to send Slack notification")

    async def close(self) -> None:
        await self._client.aclose()
