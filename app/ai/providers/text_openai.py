"""PLACEHOLDER — same TextLLMProvider interface as Gemini/Groq.

Disabled when OPENAI_API_KEY is empty (raises AI_PROVIDER_NOT_CONFIGURED).
Flip AI_TEXT_PROVIDER=openai + set key later — no caller rewrites.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from app.ai.providers.base import TextLLMProvider
from app.core.config import Settings
from app.core.exceptions import AiProviderNotConfiguredError, AppError
from app.core.logging import get_logger

log = get_logger("tactech.ai.openai")


class OpenAITextProvider(TextLLMProvider):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _ensure_key(self) -> str:
        key = (self.settings.openai_api_key or "").strip()
        if not key:
            raise AiProviderNotConfiguredError(
                "OPENAI_API_KEY is empty. Set it and AI_TEXT_PROVIDER=openai to enable paid text."
            )
        return key

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        response_json: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.settings.openai_chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._ensure_key()}"},
                json=payload,
            )
            if response.status_code >= 400:
                log.error("openai_chat_failed", status=response.status_code, body=response.text[:300])
                raise AppError("AI coach is temporarily unavailable.", status_code=502, code="AI_UPSTREAM")
            return response.json()["choices"][0]["message"]["content"].strip()

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._ensure_key()}"},
                json={
                    "model": self.settings.openai_chat_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    log.error("openai_stream_failed", status=response.status_code, body=body[:300])
                    raise AppError("AI coach is temporarily unavailable.", status_code=502, code="AI_UPSTREAM")
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        import json

                        chunk = json.loads(payload)
                        delta = chunk["choices"][0].get("delta", {}).get("content")
                        if delta:
                            yield delta
                    except Exception:
                        continue
