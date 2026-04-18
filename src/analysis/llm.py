"""Minimal provider-agnostic LLM helper.

Both Anthropic and OpenAI SDKs are supported. The helper returns the plain
response text + token usage so call sites don't need to know which SDK they
are talking to. Extractor and Scorer pass a provider flag explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int


async def complete(
    client: Any,
    provider: str,
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1024,
) -> LLMResponse:
    """Dispatch a chat/messages call to the correct SDK.

    provider: "anthropic" or "openai".
    Raises ValueError for unknown providers.
    """
    if provider == "anthropic":
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        block = resp.content[0]
        text = block.text if hasattr(block, "text") else ""
        return LLMResponse(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

    if provider == "openai":
        resp = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        choice = resp.choices[0]
        text = choice.message.content or ""
        usage = resp.usage
        return LLMResponse(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        )

    raise ValueError(f"Unknown LLM provider: {provider}")
