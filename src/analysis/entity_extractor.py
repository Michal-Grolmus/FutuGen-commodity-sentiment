from __future__ import annotations

import json
import logging
import time
from typing import Any

from src.analysis.llm import complete
from src.analysis.prompts import extraction_prompt
from src.models import (
    CommodityMention,
    EconomicIndicator,
    ExtractionResult,
    PersonMention,
    Transcript,
)

logger = logging.getLogger(__name__)


class EntityExtractor:
    def __init__(
        self,
        client: Any,
        model: str = "claude-haiku-4-5-20251001",
        provider: str = "anthropic",
    ) -> None:
        self._client = client
        self._model = model
        self._provider = provider

    async def extract(self, transcript: Transcript) -> ExtractionResult:
        if not transcript.full_text.strip():
            return self._empty_result(transcript)

        t0 = time.perf_counter()

        try:
            response = await complete(
                self._client,
                self._provider,
                model=self._model,
                system=extraction_prompt(),
                user=transcript.full_text,
                max_tokens=1024,
            )

            data = json.loads(response.text)
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
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
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
