"""Free-tier text LLM via Groq (OpenAI-compatible chat completions)."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator

import httpx

from app.ai.providers.base import TextLLMProvider
from app.core.config import Settings
from app.core.exceptions import AiProviderNotConfiguredError, AppError, RateLimitError
from app.core.logging import get_logger

log = get_logger("tactech.ai.groq")

_RETRY_AFTER_RE = re.compile(r"try again in\s+([\d.]+)\s*s", re.IGNORECASE)


def _parse_retry_after_seconds(response: httpx.Response) -> float:
    header = (response.headers.get("retry-after") or "").strip()
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    body = ""
    try:
        body = response.text or ""
    except Exception:
        body = ""
    match = _RETRY_AFTER_RE.search(body)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 5.0


class GroqTextProvider(TextLLMProvider):
    name = "groq"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _ensure_key(self) -> str:
        key = (self.settings.groq_api_key or "").strip()
        if not key:
            raise AiProviderNotConfiguredError(
                "GROQ_API_KEY is missing. Get a free key at https://console.groq.com/keys"
            )
        return key

    async def _post_with_rate_limit_retry(self, payload: dict[str, Any]) -> httpx.Response:
        """POST once; on 429 sleep (cap 15s) and retry once; persistent 429 → RateLimitError."""
        key = self._ensure_key()
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
            if response.status_code != 429:
                return response

            wait = min(15.0, max(0.5, _parse_retry_after_seconds(response)))
            wait_ms = int(wait * 1000)
            log.warning("groq_rate_limited", wait_ms=wait_ms, attempt=1)
            await asyncio.sleep(wait)

            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
            if response.status_code == 429:
                wait2 = min(15, max(1, int(_parse_retry_after_seconds(response))))
                log.warning("groq_rate_limited", wait_ms=wait2 * 1000, attempt=2)
                raise RateLimitError(
                    "AI is busy (rate limit). Wait a few seconds and try again.",
                    retry_after=wait2,
                )
            return response

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        response_json: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.settings.groq_chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}
        response = await self._post_with_rate_limit_retry(payload)
        if response.status_code >= 400:
            log.error("groq_chat_failed", status=response.status_code, body=response.text[:300])
            raise AppError("AI coach is temporarily unavailable.", status_code=502, code="AI_UPSTREAM")
        return response.json()["choices"][0]["message"]["content"].strip()

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": self.settings.groq_chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        key = self._ensure_key()

        async def _open_stream(client: httpx.AsyncClient) -> httpx.Response:
            return await client.send(
                client.build_request(
                    "POST",
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=payload,
                ),
                stream=True,
            )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await _open_stream(client)
            if response.status_code == 429:
                body = await response.aread()
                response = httpx.Response(
                    429,
                    headers=response.headers,
                    content=body,
                    request=response.request,
                )
                wait = min(15.0, max(0.5, _parse_retry_after_seconds(response)))
                log.warning("groq_rate_limited", wait_ms=int(wait * 1000), attempt=1)
                await response.aclose()
                await asyncio.sleep(wait)
                response = await _open_stream(client)
                if response.status_code == 429:
                    body2 = await response.aread()
                    await response.aclose()
                    tmp = httpx.Response(429, headers=response.headers, content=body2)
                    wait2 = min(15, max(1, int(_parse_retry_after_seconds(tmp))))
                    log.warning("groq_rate_limited", wait_ms=wait2 * 1000, attempt=2)
                    raise RateLimitError(
                        "AI is busy (rate limit). Wait a few seconds and try again.",
                        retry_after=wait2,
                    )

            if response.status_code >= 400:
                body = await response.aread()
                await response.aclose()
                log.error("groq_stream_failed", status=response.status_code, body=body[:300])
                raise AppError("AI coach is temporarily unavailable.", status_code=502, code="AI_UPSTREAM")

            try:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk_payload = line[6:].strip()
                    if chunk_payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(chunk_payload)
                        delta = chunk["choices"][0].get("delta", {}).get("content")
                        if delta:
                            yield delta
                    except Exception:
                        continue
            finally:
                await response.aclose()
