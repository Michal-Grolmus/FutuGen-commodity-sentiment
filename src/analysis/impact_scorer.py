from __future__ import annotations

import json
import logging
import time

from anthropic import AsyncAnthropic

from src.analysis.prompts import SCORING_SYSTEM_PROMPT
from src.models import CommoditySignal, Direction, ExtractionResult, ScoringResult, Timeframe
from src.prices.yahoo_client import COMMODITY_TICKERS, PriceClient

logger = logging.getLogger(__name__)


class ImpactScorer:
    def __init__(
        self,
        client: AsyncAnthropic,
        model: str = "claude-haiku-4-5-20251001",
        price_client: PriceClient | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._price_client = price_client

    async def score(self, extraction: ExtractionResult) -> ScoringResult:
        if not extraction.commodities:
            return self._empty_result(extraction)

        t0 = time.perf_counter()

        # Build context message from extraction
        context_parts = [f"Transcript: {extraction.raw_text}"]
        if extraction.commodities:
            context_parts.append(
                "Commodities mentioned: "
                + ", ".join(f"{c.display_name} ({c.context})" for c in extraction.commodities)
            )
        if extraction.people:
            context_parts.append(
                "Key people: "
                + ", ".join(f"{p.name} ({p.role or 'unknown role'})" for p in extraction.people)
            )
        if extraction.indicators:
            context_parts.append(
                "Economic indicators: "
                + ", ".join(f"{ind.display_name} ({ind.context})" for ind in extraction.indicators)
            )

        # RAG: Enrich context with current market prices from Yahoo Finance
        price_context = self._get_price_context(extraction)
        if price_context:
            context_parts.append(price_context)

        user_message = "\n\n".join(context_parts)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SCORING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            raw = response.content[0].text
            data = json.loads(raw)
            elapsed = time.perf_counter() - t0

            signals = []
            for s in data.get("signals", []):
                try:
                    signals.append(CommoditySignal(
                        commodity=s.get("commodity", "unknown"),
                        display_name=s.get("display_name", "Unknown"),
                        direction=Direction(s.get("direction", "neutral").lower()),
                        confidence=max(0.0, min(1.0, float(s.get("confidence", 0.5)))),
                        rationale=s.get("rationale", ""),
                        timeframe=Timeframe(s.get("timeframe", "short_term")),
                        source_text=s.get("source_text", ""),
                        speaker=s.get("speaker"),
                    ))
                except Exception:
                    logger.warning("Skipping invalid signal: %s", s)

            result = ScoringResult(
                chunk_id=extraction.chunk_id,
                signals=signals,
                model_used=self._model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                processing_time_s=elapsed,
            )

            for sig in signals:
                logger.info(
                    "Signal %s: %s %s (conf=%.2f) — %s",
                    extraction.chunk_id,
                    sig.commodity,
                    sig.direction.value,
                    sig.confidence,
                    sig.rationale[:80],
                )
            return result

        except json.JSONDecodeError:
            logger.error("Scoring %s: malformed JSON from LLM, returning empty", extraction.chunk_id)
            return self._empty_result(extraction, time.perf_counter() - t0)
        except Exception:
            logger.exception("Scoring %s: unexpected error", extraction.chunk_id)
            return self._empty_result(extraction, time.perf_counter() - t0)

    def _get_price_context(self, extraction: ExtractionResult) -> str:
        """RAG: Retrieve current commodity prices to enrich LLM scoring context."""
        if not self._price_client:
            return ""

        price_lines = []
        for commodity in extraction.commodities:
            if commodity.name in COMMODITY_TICKERS:
                price = self._price_client.get_current_price(commodity.name)
                change = self._price_client.get_price_change_24h(commodity.name)
                if price is not None:
                    line = f"  {commodity.display_name}: ${price:.2f}"
                    if change is not None:
                        direction = "+" if change >= 0 else ""
                        line += f" ({direction}{change:.2f} 24h)"
                    price_lines.append(line)

        if not price_lines:
            return ""

        return "Current market prices (RAG context):\n" + "\n".join(price_lines)

    def _empty_result(self, extraction: ExtractionResult, elapsed: float = 0.0) -> ScoringResult:
        return ScoringResult(
            chunk_id=extraction.chunk_id,
            signals=[],
            model_used=self._model,
            input_tokens=0,
            output_tokens=0,
            processing_time_s=elapsed,
        )
