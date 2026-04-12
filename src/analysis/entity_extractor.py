from __future__ import annotations

import json
import logging
import time

from anthropic import AsyncAnthropic

from src.analysis.prompts import EXTRACTION_SYSTEM_PROMPT
from src.models import (
    CommodityMention,
    EconomicIndicator,
    ExtractionResult,
    PersonMention,
    Transcript,
)

logger = logging.getLogger(__name__)


class EntityExtractor:
    def __init__(self, client: AsyncAnthropic, model: str = "claude-haiku-4-5-20251001") -> None:
        self._client = client
        self._model = model

    async def extract(self, transcript: Transcript) -> ExtractionResult:
        if not transcript.full_text.strip():
            return self._empty_result(transcript)

        t0 = time.perf_counter()

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=EXTRACTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": transcript.full_text}],
            )

            raw = response.content[0].text
            data = json.loads(raw)
            elapsed = time.perf_counter() - t0

            commodities = []
            for c in data.get("commodities", []):
                try:
                    commodities.append(CommodityMention(**c))
                except Exception:
                    logger.warning("Skipping invalid commodity mention: %s", c)

            people = []
            for p in data.get("people", []):
                try:
                    people.append(PersonMention(**p))
                except Exception:
                    logger.warning("Skipping invalid person mention: %s", p)

            indicators = []
            for ind in data.get("indicators", []):
                try:
                    indicators.append(EconomicIndicator(**ind))
                except Exception:
                    logger.warning("Skipping invalid indicator: %s", ind)

            result = ExtractionResult(
                chunk_id=transcript.chunk_id,
                commodities=commodities,
                people=people,
                indicators=indicators,
                raw_text=transcript.full_text,
                model_used=self._model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                processing_time_s=elapsed,
            )

            logger.info(
                "Extraction %s: %d commodities, %d people, %d indicators (%.2fs)",
                transcript.chunk_id,
                len(result.commodities),
                len(result.people),
                len(result.indicators),
                elapsed,
            )
            return result

        except json.JSONDecodeError:
            logger.error("Extraction %s: malformed JSON from LLM, returning empty result", transcript.chunk_id)
            return self._empty_result(transcript, time.perf_counter() - t0)
        except Exception:
            logger.exception("Extraction %s: unexpected error", transcript.chunk_id)
            return self._empty_result(transcript, time.perf_counter() - t0)

    def _empty_result(self, transcript: Transcript, elapsed: float = 0.0) -> ExtractionResult:
        return ExtractionResult(
            chunk_id=transcript.chunk_id,
            commodities=[],
            people=[],
            indicators=[],
            raw_text=transcript.full_text,
            model_used=self._model,
            input_tokens=0,
            output_tokens=0,
            processing_time_s=elapsed,
        )
