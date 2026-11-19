"""Active free-tier text LLM — Google Gemini Flash."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx

from app.ai.providers.base import TextLLMProvider
from app.core.config import Settings
from app.core.exceptions import AiProviderNotConfiguredError, AppError, RateLimitError
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
        model = (self.settings.gemini_chat_model or "gemini-3.8-flash").strip()
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

    async def _post_with_retry(self, url: str, body: dict[str, Any]) -> httpx.Response:
        """POST with one retry on 429 (rate limit)."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=body)
            if response.status_code != 429:
                return response
            wait = min(10.0, max(1.0, float(response.headers.get("retry-after", "3"))))
            log.warning("gemini_rate_limited", wait_s=wait, attempt=1)
            await asyncio.sleep(wait)
            response = await client.post(url, json=body)
            if response.status_code == 429:
                log.warning("gemini_rate_limited", wait_s=wait, attempt=2)
                raise RateLimitError(
                    "AI is busy (rate limit). Wait a few seconds and try again.",
                    retry_after=int(wait),
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
        response = await self._post_with_retry(
            self._url(stream=False),
            self._body(messages, temperature=temperature, max_tokens=max_tokens, response_json=response_json),
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

    @staticmethod
    def _openai_tools_to_gemini(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI-format tool defs to Gemini function declarations."""
        declarations = []
        for t in tools:
            fn = t.get("function", {})
            params = dict(fn.get("parameters", {}))
            params.pop("required", None)
            declarations.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": params,
            })
        return declarations

    @staticmethod
    def _gemini_tool_calls_to_openai(parts: list[dict]) -> list[dict] | None:
        """Convert Gemini functionCall parts to OpenAI-format tool_calls.
        Preserves raw Gemini parts in _gemini_raw_parts for replay."""
        calls = []
        for i, p in enumerate(parts):
            fc = p.get("functionCall")
            if fc:
                tc_id = fc.get("id") or f"call_{i}"
                calls.append({
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": fc["name"],
                        "arguments": json.dumps(fc.get("args", {})),
                    },
                    "_gemini_part": p,
                })
        return calls or None

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        system, contents = _to_gemini_contents(messages)

        # Append tool role messages (tool results back to Gemini)
        # Rebuild contents to handle assistant tool_calls and tool results
        rebuilt: list[dict[str, Any]] = []
        for msg in messages:
            role = (msg.get("role") or "user").lower()
            if role == "system":
                continue
            if role == "assistant" and msg.get("tool_calls"):
                parts = []
                if msg.get("content"):
                    parts.append({"text": msg["content"]})
                for tc in msg["tool_calls"]:
                    raw = tc.get("_gemini_part")
                    if raw:
                        parts.append(raw)
                    else:
                        fn = tc["function"]
                        args = fn.get("arguments", "{}")
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except (json.JSONDecodeError, TypeError):
                                args = {}
                        parts.append({"functionCall": {"name": fn["name"], "args": args}})
                rebuilt.append({"role": "model", "parts": parts})
            elif role == "tool":
                content = msg.get("content", "")
                try:
                    response_data = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    response_data = {"result": content}
                # Gemini requires response to be an object, not a list
                if isinstance(response_data, list):
                    response_data = {"items": response_data}
                elif not isinstance(response_data, dict):
                    response_data = {"result": response_data}
                # Find the tool name from the tool_call_id in previous messages
                tool_name = msg.get("_tool_name", "unknown")
                if tool_name == "unknown":
                    tc_id = msg.get("tool_call_id", "")
                    for prev in messages:
                        for tc in prev.get("tool_calls", []):
                            if tc.get("id") == tc_id:
                                tool_name = tc["function"]["name"]
                                break
                rebuilt.append({
                    "role": "user",
                    "parts": [{"functionResponse": {"name": tool_name, "response": response_data}}],
                })
            else:
                gemini_role = "model" if role == "assistant" else "user"
                rebuilt.append({"role": gemini_role, "parts": [{"text": str(msg.get("content", ""))}]})

        if not rebuilt:
            rebuilt = [{"role": "user", "parts": [{"text": "Hello"}]}]

        body: dict[str, Any] = {
            "contents": rebuilt,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
            "tools": [{"functionDeclarations": self._openai_tools_to_gemini(tools)}],
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        response = await self._post_with_retry(self._url(stream=False), body)
        if response.status_code >= 400:
            log.error("gemini_tools_failed", status=response.status_code, body=response.text[:400])
            raise AppError("AI coach is temporarily unavailable.", status_code=502, code="AI_UPSTREAM")
        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text_parts = [p.get("text", "") for p in parts if "text" in p]
            content = "".join(text_parts).strip() or None
            tool_calls = self._gemini_tool_calls_to_openai(parts)
            return {"content": content, "tool_calls": tool_calls}
        except (KeyError, IndexError, TypeError) as exc:
            log.error("gemini_tools_parse_failed", body=str(data)[:400])
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
