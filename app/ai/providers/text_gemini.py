"""Active free-tier text LLM — Google Gemini Flash."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.ai.providers.base import TextLLMProvider
from app.core.config import Settings
from app.core.exceptions import AiProviderNotConfiguredError, AppError
from app.core.logging import get_logger

log = get_logger("tactech.ai.gemini")


def _to_gemini_contents(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for msg in messages:
        role = (msg.get("role") or "user").lower()
        content = msg.get("content") or ""
        if role == "system":
            system_parts.append(str(content))
            continue
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": str(content)}]})
    system = "\n\n".join(system_parts).strip() or None
    return system, contents


class GeminiTextProvider(TextLLMProvider):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _ensure_key(self) -> str:
        key = (self.settings.gemini_api_key or "").strip()
        if not key:
            raise AiProviderNotConfiguredError(
                "GEMINI_API_KEY is missing. Get a free key at https://aistudio.google.com/apikey"
            )
        return key

    def _url(self, *, stream: bool = False) -> str:
        model = (self.settings.gemini_chat_model or "gemini-2.0-flash").strip()
        method = "streamGenerateContent" if stream else "generateContent"
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:{method}"
            f"?key={self._ensure_key()}"
        )

    def _body(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        response_json: bool,
    ) -> dict[str, Any]:
        system, contents = _to_gemini_contents(messages)
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello"}]}]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if response_json:
            body["generationConfig"]["responseMimeType"] = "application/json"
        return body

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        response_json: bool = False,
    ) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                self._url(stream=False),
                json=self._body(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_json=response_json,
                ),
            )
            if response.status_code >= 400:
                log.error("gemini_chat_failed", status=response.status_code, body=response.text[:400])
                raise AppError("AI coach is temporarily unavailable.", status_code=502, code="AI_UPSTREAM")
            data = response.json()
            try:
                parts = data["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts).strip()
            except (KeyError, IndexError, TypeError) as exc:
                log.error("gemini_parse_failed", body=str(data)[:400])
                raise AppError("AI coach is temporarily unavailable.", status_code=502, code="AI_UPSTREAM") from exc

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        url = self._url(stream=True) + "&alt=sse"
        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream(
                "POST",
                url,
                json=self._body(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_json=False,
                ),
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    log.error("gemini_stream_failed", status=response.status_code, body=body[:400])
                    raise AppError("AI coach is temporarily unavailable.", status_code=502, code="AI_UPSTREAM")
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(payload)
                        parts = chunk["candidates"][0]["content"]["parts"]
                        for part in parts:
                            text = part.get("text")
                            if text:
                                yield text
                    except Exception:
                        continue
