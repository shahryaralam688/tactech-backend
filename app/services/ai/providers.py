from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import httpx

from app.core.config import Settings
from app.core.exceptions import AppError, RateLimitError, ValidationAppError
from app.core.logging import get_logger

log = get_logger("tactech.ai")

EMBED_DIM = 1536
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def _data_url(image_bytes: bytes, content_type: str | None) -> str:
    mime = (content_type or "image/jpeg").split(";")[0].strip().lower()
    if mime not in {"image/jpeg", "image/jpg", "image/png", "image/webp"}:
        mime = "image/jpeg"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _raise_for_openai(response: httpx.Response, *, fallback: str, code: str) -> None:
    if response.status_code < 400:
        return
    body = (response.text or "")[:400]
    log.error("openai_upstream_failed", status=response.status_code, body=body, code=code)
    lowered = body.lower()
    if response.status_code == 429 or "insufficient_quota" in lowered or "credit_balance" in lowered:
        if "insufficient_quota" in lowered or "credit_balance" in lowered:
            raise RateLimitError(
                "OpenAI account has no credits left. Add billing credits, or switch AI_PROVIDER back to groq for free demo."
            )
        raise RateLimitError(
            "OpenAI rate limit hit. Wait ~20–60 seconds and try again "
            "(voice uses Whisper which has a lower free/tier limit)."
        )
    if response.status_code in {401, 403}:
        raise AppError("OpenAI API key is invalid or blocked.", status_code=503, code="AI_NOT_CONFIGURED")
    raise AppError(fallback, status_code=502, code=code)


async def _openai_post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any] | None = None,
    files: Any = None,
    data: Any = None,
    retries: int = 3,
) -> httpx.Response:
    last: httpx.Response | None = None
    for attempt in range(retries):
        # Rebuild multipart each attempt — httpx file tuples are single-use
        response = await client.post(url, headers=headers, json=json, files=files, data=data)
        last = response
        if response.status_code != 429:
            return response
        retry_after = response.headers.get("retry-after")
        try:
            delay = float(retry_after) if retry_after else (1.5 * (2**attempt))
        except ValueError:
            delay = 1.5 * (2**attempt)
        delay = min(max(delay, 1.0), 20.0)
        log.warning("openai_rate_limited_retrying", attempt=attempt + 1, delay=delay)
        if attempt < retries - 1:
            await asyncio.sleep(delay)
    assert last is not None
    return last


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class LocalHashEmbedding(EmbeddingProvider):
    def __init__(self, dim: int = EMBED_DIM) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return vec
        for token in tokens:
            digest = hashlib.sha256(token.encode()).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        for i in range(len(tokens) - 1):
            gram = f"{tokens[i]}_{tokens[i + 1]}"
            digest = hashlib.sha256(gram.encode()).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += 0.5 * sign
        return _l2_normalize(vec)


class OpenAIEmbedding(EmbeddingProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = LocalHashEmbedding()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.settings.openai_api_key:
            return await self._fallback.embed(texts)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.openai_embedding_model,
                    "input": texts,
                    "dimensions": self.settings.ai_embedding_dimensions,
                },
            )
            if response.status_code >= 400:
                log.warning("openai_embed_failed", status=response.status_code)
                return await self._fallback.embed(texts)
            data = response.json()["data"]
            data.sort(key=lambda row: row["index"])
            return [row["embedding"] for row in data]


class ChatProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int) -> str:
        raise NotImplementedError

    async def stream(
        self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        text = await self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        size = 24
        for i in range(0, len(text), size):
            yield text[i : i + size]


class VisionProvider(ABC):
    @abstractmethod
    async def analyze(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_bytes: bytes,
        content_type: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        raise NotImplementedError


class GroqChatProvider(ChatProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int) -> str:
        if not self.settings.groq_api_key:
            raise AppError(
                "GROQ_API_KEY is missing. Get a free key at https://console.groq.com/keys",
                status_code=503,
                code="AI_NOT_CONFIGURED",
            )
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
                json={
                    "model": self.settings.groq_chat_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            if response.status_code >= 400:
                log.error("groq_chat_failed", status=response.status_code, body=response.text[:300])
                raise AppError("AI coach is temporarily unavailable.", status_code=502, code="AI_UPSTREAM")
            return response.json()["choices"][0]["message"]["content"].strip()

    async def stream(
        self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        if not self.settings.groq_api_key:
            raise AppError(
                "GROQ_API_KEY is missing. Get a free key at https://console.groq.com/keys",
                status_code=503,
                code="AI_NOT_CONFIGURED",
            )
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
                json={
                    "model": self.settings.groq_chat_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    log.error("groq_stream_failed", status=response.status_code, body=body[:300])
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


class GroqVisionProvider(VisionProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = MockVisionProvider()

    async def analyze(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_bytes: bytes,
        content_type: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        if not self.settings.groq_api_key:
            return await self._fallback.analyze(
                system_prompt=system_prompt,
                user_text=user_text,
                image_bytes=image_bytes,
                content_type=content_type,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": _data_url(image_bytes, content_type)},
                    },
                ],
            },
        ]
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
                json={
                    "model": self.settings.groq_vision_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            if response.status_code >= 400:
                log.warning("groq_vision_failed_using_mock", status=response.status_code, body=response.text[:300])
                return await self._fallback.analyze(
                    system_prompt=system_prompt,
                    user_text=user_text,
                    image_bytes=image_bytes,
                    content_type=content_type,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            return response.json()["choices"][0]["message"]["content"].strip()


class OpenAIChatProvider(ChatProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int) -> str:
        if not self.settings.openai_api_key:
            raise AppError("OPENAI_API_KEY is missing.", status_code=503, code="AI_NOT_CONFIGURED")
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await _openai_post_with_retry(
                client,
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.openai_chat_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            _raise_for_openai(response, fallback="AI coach is temporarily unavailable.", code="AI_UPSTREAM")
            return response.json()["choices"][0]["message"]["content"].strip()

    async def stream(
        self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        if not self.settings.openai_api_key:
            raise AppError("OPENAI_API_KEY is missing.", status_code=503, code="AI_NOT_CONFIGURED")
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.openai_chat_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="ignore")
                    lowered = body.lower()
                    if response.status_code == 429 or "insufficient_quota" in lowered:
                        if "insufficient_quota" in lowered or "credit_balance" in lowered:
                            raise RateLimitError(
                                "OpenAI account has no credits left. Add billing credits, "
                                "or switch AI_PROVIDER=groq for free demo."
                            )
                        raise RateLimitError(
                            "OpenAI rate limit hit. Wait ~20–60 seconds and try again."
                        )
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


class OpenAIVisionProvider(VisionProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def analyze(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_bytes: bytes,
        content_type: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        if not self.settings.openai_api_key:
            raise AppError("OPENAI_API_KEY is missing.", status_code=503, code="AI_NOT_CONFIGURED")
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": _data_url(image_bytes, content_type)},
                    },
                ],
            },
        ]
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await _openai_post_with_retry(
                client,
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.openai_vision_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            _raise_for_openai(response, fallback="Could not analyze the image.", code="AI_VISION_FAILED")
            return response.json()["choices"][0]["message"]["content"].strip()


class MockChatProvider(ChatProvider):
    """Zero-cost offline coach that still uses RAG memory context."""

    async def complete(self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int) -> str:
        user = ""
        for m in reversed(messages):
            if m.get("role") != "user":
                continue
            content = m.get("content")
            if isinstance(content, str):
                user = content
            elif isinstance(content, list):
                user = " ".join(
                    part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
                )
            break

        context = next((str(m.get("content", "")) for m in messages if m.get("role") == "system"), "")
        facts = [
            line[2:].strip()
            for line in context.splitlines()
            if line.startswith("- ") and len(line) > 4 and "no saved context" not in line.lower()
        ][:4]

        q = user.lower()
        hinglish = any(
            w in q for w in ("kya", "hai", "aaj", "mujhe", "trainees", "karo", "batao", "chahiye", "kaise")
        )

        if facts:
            bit = facts[0][:140]
            extra = f" Also: {facts[1][:110]}" if len(facts) > 1 else ""
            if any(w in q for w in ("meal", "calorie", "protein", "khana", "diet")):
                if hinglish:
                    return (
                        f"Bilkul — nutrition pe focus rakho. Mere notes: {bit}.{extra} "
                        f"Aaj simple rule: protein pehle, portion control, water. "
                        f"“{user[:80]}” pe consistency rakho. Meal log bhejoge?"
                    )
                return (
                    f"Got it. From your profile: {bit}.{extra} "
                    f"For “{user[:90]}” — protein first, steady portions. Want me to check today’s macros?"
                )
            if any(w in q for w in ("workout", "train", "plan", "exercise", "form", "squat", "focus")):
                if hinglish:
                    return (
                        f"Sun — aaj ka focus clear hai. Context: {bit}.{extra} "
                        f"“{user[:80]}” pe: quality reps, solid brace, assigned plan clean complete karo. "
                        "Kaunsa lift tight feel ho raha hai?"
                    )
                return (
                    f"Alright — based on {bit}.{extra} "
                    f"For “{user[:90]}”, stick to the plan and chase clean reps over ego load. "
                    "Which lift feels stickiest today?"
                )
            if hinglish:
                return (
                    f"Samajh gaya. Tere data se: {bit}.{extra} "
                    f"“{user[:90]}” — simple raho, plan follow karo, recovery skip mat karo. Aur detail chahiye?"
                )
            return (
                f"I hear you. From what I know: {bit}.{extra} "
                f"On “{user[:90]}” — keep it simple, stick to the plan, protect recovery. Ask me anything more specific."
            )

        if hinglish:
            return (
                f"Message mil gaya: “{user[:120]}”. Memory thin hai — sync/refresh kar lo "
                "taake main tere plan se personal jawab doon. Tab tak hydrate + protein + intentional session."
            )
        return (
            f"Got your note: “{user[:120]}”. Sync coach memory once so I can answer from your real plan. "
            "Until then: hydrate, hit protein, keep today’s session intentional."
        )


class MockVisionProvider(VisionProvider):
    async def analyze(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_bytes: bytes,
        content_type: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        prompt = (user_text or "").lower()
        hinglish = any(w in prompt for w in ("kya", "hai", "dekh", "form", "check", "batao"))
        if any(word in prompt for word in ("meal", "food", "plate", "lunch", "dinner", "breakfast", "khana")):
            if hinglish:
                return (
                    "Photo mil gayi — meal lag rahi hai. Protein pehle, carbs portion me, "
                    "calorie target ke qareeb raho. Portion batao to better estimate dunga."
                )
            return (
                "Looks like a meal shot. Protein first, watch carb portions, stay near your calorie target. "
                "Share portion size for a tighter estimate."
            )
        if any(word in prompt for word in ("form", "squat", "deadlift", "lift", "pose", "exercise")):
            if hinglish:
                return (
                    "Form check: core tight, spine neutral, control se neeche. "
                    "Balance wobbly ho to weight 5–10% kam. Side angle next time best."
                )
            return (
                "Form check: brace hard, neutral spine, own the eccentric. "
                "If balance feels off, drop load 5–10%. Side-angle clip next time helps."
            )
        if hinglish:
            return (
                f"Image aa gayi. Form, meal, ya progress pe feedback de sakta hoon. "
                f"Exact kya check karna hai? (“{(user_text or 'analyze')[:70]}”)"
            )
        return (
            f"Got the photo. I can coach form, meals, or progress — "
            f"what should I focus on? (“{(user_text or 'analyze this')[:70]}”)"
        )


class HuggingFaceChatProvider(ChatProvider):
    """Free Hugging Face Inference (OpenAI-compatible router). Needs HF_TOKEN.

    On monthly credit exhaustion (402), falls back to local mock so the app keeps working.
    """

    _credits_exhausted = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = MockChatProvider()

    async def complete(self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int) -> str:
        if HuggingFaceChatProvider._credits_exhausted:
            return await self._fallback.complete(messages, temperature=temperature, max_tokens=max_tokens)
        if not self.settings.hf_token:
            raise AppError(
                "HF_TOKEN missing. Free token: https://huggingface.co/settings/tokens",
                status_code=503,
                code="AI_NOT_CONFIGURED",
            )
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.hf_token}"},
                json={
                    "model": self.settings.hf_chat_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            if response.status_code >= 400:
                body = response.text[:400]
                log.error("hf_chat_failed", status=response.status_code, body=body)
                lowered = body.lower()
                if (
                    response.status_code in {402, 429}
                    or "depleted" in lowered
                    or "credits" in lowered
                    or "payment required" in lowered
                ):
                    HuggingFaceChatProvider._credits_exhausted = True
                    log.warning("hf_credits_exhausted_falling_back_to_mock")
                    return await self._fallback.complete(
                        messages, temperature=temperature, max_tokens=max_tokens
                    )
                raise AppError(
                    "Hugging Face coach unavailable right now. Try again shortly.",
                    status_code=502,
                    code="AI_UPSTREAM",
                )
            return response.json()["choices"][0]["message"]["content"].strip()

    async def stream(
        self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        # HF stream support varies — fall back to chunked complete for reliability
        text = await self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        size = 28
        for i in range(0, len(text), size):
            yield text[i : i + size]


class HuggingFaceVisionProvider(VisionProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = MockVisionProvider()

    async def analyze(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_bytes: bytes,
        content_type: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        if not self.settings.hf_token:
            return await self._fallback.analyze(
                system_prompt=system_prompt,
                user_text=user_text,
                image_bytes=image_bytes,
                content_type=content_type,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": _data_url(image_bytes, content_type)}},
                ],
            },
        ]
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.hf_token}"},
                json={
                    "model": self.settings.hf_vision_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            if response.status_code >= 400:
                log.warning("hf_vision_failed", status=response.status_code, body=response.text[:300])
                if response.status_code in {402, 429}:
                    HuggingFaceChatProvider._credits_exhausted = True
                return await self._fallback.analyze(
                    system_prompt=system_prompt,
                    user_text=user_text,
                    image_bytes=image_bytes,
                    content_type=content_type,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            return response.json()["choices"][0]["message"]["content"].strip()


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes, filename: str, content_type: str | None) -> str:
        raise NotImplementedError


class GroqSTTProvider(STTProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def transcribe(self, audio: bytes, filename: str, content_type: str | None) -> str:
        if not self.settings.groq_api_key:
            raise AppError(
                "GROQ_API_KEY is missing for voice transcription.",
                status_code=503,
                code="AI_NOT_CONFIGURED",
            )
        files = {"file": (filename or "audio.m4a", audio, content_type or "audio/m4a")}
        data = {"model": self.settings.groq_stt_model, "response_format": "json"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
                files=files,
                data=data,
            )
            if response.status_code >= 400:
                log.error("groq_stt_failed", status=response.status_code, body=response.text[:300])
                raise AppError("Could not transcribe audio.", status_code=502, code="AI_STT_FAILED")
            text = (response.json().get("text") or "").strip()
            if not text:
                raise ValidationAppError("No speech detected. Try again.")
            return text


class OpenAISTTProvider(STTProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def transcribe(self, audio: bytes, filename: str, content_type: str | None) -> str:
        if not self.settings.openai_api_key:
            raise AppError("OPENAI_API_KEY is missing.", status_code=503, code="AI_NOT_CONFIGURED")
        # Keep clips short — Whisper free/tier RPM is tight
        if len(audio) > 3 * 1024 * 1024:
            raise ValidationAppError("Voice clip is too large. Keep recordings under ~30 seconds.")
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        data = {"model": self.settings.openai_stt_model, "response_format": "json"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            last: httpx.Response | None = None
            for attempt in range(3):
                files = {"file": (filename or "audio.m4a", audio, content_type or "audio/m4a")}
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                )
                last = response
                if response.status_code != 429:
                    break
                delay = min(1.5 * (2**attempt), 20.0)
                log.warning("openai_stt_rate_limited_retrying", attempt=attempt + 1, delay=delay)
                if attempt < 2:
                    await asyncio.sleep(delay)
            assert last is not None
            _raise_for_openai(last, fallback="Could not transcribe audio.", code="AI_STT_FAILED")
            text = (last.json().get("text") or "").strip()
            if not text:
                raise ValidationAppError("No speech detected. Try again.")
            return text


class MockSTTProvider(STTProvider):
    async def transcribe(self, audio: bytes, filename: str, content_type: str | None) -> str:
        return "How should I train today based on my plan?"


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> tuple[bytes, str]:
        raise NotImplementedError


class EdgeTTSProvider(TTSProvider):
    def __init__(self, settings: Settings) -> None:
        self.voice = settings.ai_tts_voice

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        try:
            import edge_tts
        except ImportError as exc:
            raise AppError("edge-tts is not installed.", status_code=500, code="TTS_MISSING") from exc
        try:
            communicate = edge_tts.Communicate(text[:1200], self.voice)
            chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            if not chunks:
                raise AppError("TTS produced no audio.", status_code=502, code="AI_TTS_FAILED")
            return b"".join(chunks), ".mp3"
        except AppError:
            raise
        except Exception as exc:
            log.warning("edge_tts_failed", error=str(exc)[:240])
            raise AppError("TTS temporarily unavailable.", status_code=502, code="AI_TTS_FAILED") from exc


class OpenAITTSProvider(TTSProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        if not self.settings.openai_api_key:
            raise AppError("OPENAI_API_KEY is missing.", status_code=503, code="AI_NOT_CONFIGURED")
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await _openai_post_with_retry(
                client,
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.openai_tts_model,
                    "voice": "alloy",
                    "input": text[:800],
                },
            )
            _raise_for_openai(response, fallback="TTS failed.", code="AI_TTS_FAILED")
            return response.content, ".mp3"


class NullTTSProvider(TTSProvider):
    async def synthesize(self, text: str) -> tuple[bytes, str]:
        return b"", ".mp3"


def resolve_ai_provider(settings: Settings) -> str:
    """Pick a free provider. OpenAI only when explicitly set (never via auto)."""
    requested = (settings.ai_provider or "auto").lower().strip()
    if requested == "auto":
        # Prefer Groq when available (larger free tier). Skip HF if monthly credits exhausted.
        hf_ok = settings.hf_token.strip() and not getattr(
            HuggingFaceChatProvider, "_credits_exhausted", False
        )
        if settings.groq_api_key.strip():
            return "groq"
        if hf_ok:
            return "huggingface"
        return "mock"
    if requested == "huggingface" and not settings.hf_token.strip():
        log.warning("hf_token_missing_falling_back_to_mock")
        return "mock"
    if requested == "groq" and not settings.groq_api_key.strip():
        log.warning("groq_key_missing_falling_back_to_mock")
        return "mock"
    if requested == "openai" and not settings.openai_api_key.strip():
        log.warning("openai_key_missing_falling_back_to_mock")
        return "mock"
    return requested


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    # Free by default: local hashing into pgvector. OpenAI embeddings only if key present and provider openai.
    if settings.openai_api_key.strip() and resolve_ai_provider(settings) == "openai":
        return OpenAIEmbedding(settings)
    return LocalHashEmbedding(dim=settings.ai_embedding_dimensions)


def build_chat_provider(settings: Settings) -> ChatProvider:
    provider = resolve_ai_provider(settings)
    if provider == "huggingface":
        return HuggingFaceChatProvider(settings)
    if provider == "openai":
        return OpenAIChatProvider(settings)
    if provider == "groq":
        return GroqChatProvider(settings)
    return MockChatProvider()


def build_vision_provider(settings: Settings) -> VisionProvider:
    provider = resolve_ai_provider(settings)
    if provider == "huggingface":
        return HuggingFaceVisionProvider(settings)
    if provider == "openai":
        return OpenAIVisionProvider(settings)
    if provider == "groq":
        if settings.groq_api_key.strip():
            return GroqVisionProvider(settings)
        return MockVisionProvider()
    return MockVisionProvider()


def build_stt_provider(settings: Settings) -> STTProvider:
    provider = resolve_ai_provider(settings)
    # Free STT: Groq Whisper if key exists; else mock (app can also do on-device speech)
    if settings.groq_api_key.strip():
        return GroqSTTProvider(settings)
    if provider == "openai" and settings.openai_api_key.strip():
        return OpenAISTTProvider(settings)
    return MockSTTProvider()


def build_tts_provider(settings: Settings) -> TTSProvider:
    kind = (settings.ai_tts_provider or "edge").lower()
    if kind == "openai" and settings.openai_api_key.strip():
        return OpenAITTSProvider(settings)
    if kind in {"none", "off", "null"}:
        return NullTTSProvider()
    return EdgeTTSProvider(settings)


def provider_status(settings: Settings) -> dict[str, Any]:
    active = resolve_ai_provider(settings)
    hf_exhausted = bool(getattr(HuggingFaceChatProvider, "_credits_exhausted", False))
    chat_model = {
        "huggingface": settings.hf_chat_model,
        "openai": settings.openai_chat_model,
        "groq": settings.groq_chat_model,
        "mock": "local-mock-rag",
    }.get(active, settings.groq_chat_model)
    vision_model = {
        "huggingface": settings.hf_vision_model,
        "openai": settings.openai_vision_model,
        "groq": settings.groq_vision_model,
        "mock": "local-mock-vision",
    }.get(active, settings.groq_vision_model)
    return {
        "provider": "mock" if (active == "huggingface" and hf_exhausted) else active,
        "requestedProvider": settings.ai_provider,
        "chatConfigured": True,
        "usingMockFallback": active == "mock" or hf_exhausted,
        "hfCreditsExhausted": hf_exhausted,
        "ttsProvider": (
            "edge"
            if settings.ai_tts_provider == "openai" and not settings.openai_api_key.strip()
            else settings.ai_tts_provider
        ),
        "embedding": (
            "pgvector+openai"
            if settings.openai_api_key.strip() and active == "openai"
            else "pgvector+local"
        ),
        "vectorStore": "pgvector",
        "embeddingDimensions": settings.ai_embedding_dimensions,
        "chatModel": "local-mock-rag" if hf_exhausted else chat_model,
        "visionModel": "local-mock-vision" if hf_exhausted else vision_model,
        "supportsImages": True,
        "freeTier": {
            "mock": "no key needed",
            "huggingface": "https://huggingface.co/settings/tokens",
            "groq": "https://console.groq.com/keys",
        },
    }
