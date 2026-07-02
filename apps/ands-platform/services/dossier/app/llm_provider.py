"""Open-weight LLM chat completions (Groq-hosted Llama) for interactive
document drafting. A thin adapter over Groq's OpenAI-compatible streaming
chat API — kept separate from the domain/service layers per the hexagonal
seam (this is the only module that knows about the external HTTP call).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from .config import Settings

_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class LlmNotConfigured(Exception):
    """Raised when GROQ_API_KEY isn't set — callers should surface this as a
    clean 'not configured' response rather than a broken stream."""


def is_configured(settings: Settings | None = None) -> bool:
    return bool((settings or Settings()).groq_api_key)


async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    """Yield assistant text deltas for a chat completion, streamed token by
    token from Groq. Raises LlmNotConfigured / RuntimeError on setup errors
    (call is_configured() first to fail before any streaming starts)."""
    settings = Settings()
    if not settings.groq_api_key:
        raise LlmNotConfigured("GROQ_API_KEY is not set")

    payload = {
        "model": settings.groq_model,
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", _CHAT_URL, json=payload,
                                 headers=headers) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RuntimeError(
                    f"Groq API error {resp.status_code}: "
                    f"{body.decode(errors='replace')[:500]}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                text = delta.get("content")
                if text:
                    yield text
