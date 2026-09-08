from __future__ import annotations

import base64
import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import httpx

from app.core.config import Settings
from app.core.exceptions import AppError, ValidationAppError
from app.core.logging import get_logger

log = get_logger("tactech.ai")

EMBED_DIM = 384
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
                json={"model": self.settings.openai_embedding_model, "input": texts},
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
            raise AppError(
                "GROQ_API_KEY is missing for image analysis.",
                status_code=503,
                code="AI_NOT_CONFIGURED",
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
                log.error("groq_vision_failed", status=response.status_code, body=response.text[:400])
                raise AppError("Could not analyze the image.", status_code=502, code="AI_VISION_FAILED")
            return response.json()["choices"][0]["message"]["content"].strip()


class OpenAIChatProvider(ChatProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int) -> str:
        if not self.settings.openai_api_key:
            raise AppError("OPENAI_API_KEY is missing.", status_code=503, code="AI_NOT_CONFIGURED")
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.openai_chat_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            if response.status_code >= 400:
                log.error("openai_chat_failed", status=response.status_code, body=response.text[:300])
                raise AppError("AI coach is temporarily unavailable.", status_code=502, code="AI_UPSTREAM")
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
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.openai_vision_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            if response.status_code >= 400:
                log.error("openai_vision_failed", status=response.status_code, body=response.text[:400])
                raise AppError("Could not analyze the image.", status_code=502, code="AI_VISION_FAILED")
            return response.json()["choices"][0]["message"]["content"].strip()


class MockChatProvider(ChatProvider):
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
        context = next((m["content"] for m in messages if m.get("role") == "system"), "")
        snippet = ""
        for line in str(context).splitlines():
            if line.startswith("- ") and len(line) > 4:
                snippet = line[2:].strip()
                break
        if snippet:
            return (
                f"Based on your profile data ({snippet[:160]}), here's my coaching take on "
                f"“{user[:120]}”: stay consistent with your current plan, prioritize recovery, "
                "and progress load only when form feels solid."
            )
        return (
            f"I hear you: “{user[:160]}”. Sync coach memory once so I can personalize from your data."
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
        size_kb = max(1, len(image_bytes) // 1024)
        prompt = (user_text or "").lower()
        if any(word in prompt for word in ("meal", "food", "plate", "lunch", "dinner", "breakfast")):
            return (
                f"(Demo vision · {size_kb}KB) Looks like a meal photo. Stay near your calorie target, "
                "add lean protein if carb-heavy, and log the portion."
            )
        if any(word in prompt for word in ("form", "squat", "deadlift", "lift", "pose", "exercise")):
            return (
                f"(Demo vision · {size_kb}KB) Form check: brace core, neutral spine, control the eccentric. "
                "Film a side angle next time; reduce load 5–10% if depth looks off."
            )
        return (
            f"(Demo vision · {size_kb}KB) Image received. I can review form, meals, progress photos, "
            f"or equipment. What feedback do you want? (“{(user_text or 'analyze this')[:80]}”)."
        )


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
        files = {"file": (filename or "audio.m4a", audio, content_type or "audio/m4a")}
        data = {"model": self.settings.openai_stt_model, "response_format": "json"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                files=files,
                data=data,
            )
            if response.status_code >= 400:
                raise AppError("Could not transcribe audio.", status_code=502, code="AI_STT_FAILED")
            text = (response.json().get("text") or "").strip()
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
        communicate = edge_tts.Communicate(text[:1200], self.voice)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        if not chunks:
            raise AppError("TTS produced no audio.", status_code=502, code="AI_TTS_FAILED")
        return b"".join(chunks), ".mp3"


class OpenAITTSProvider(TTSProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        if not self.settings.openai_api_key:
            raise AppError("OPENAI_API_KEY is missing.", status_code=503, code="AI_NOT_CONFIGURED")
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.openai_tts_model,
                    "voice": "alloy",
                    "input": text[:1200],
                },
            )
            if response.status_code >= 400:
                raise AppError("TTS failed.", status_code=502, code="AI_TTS_FAILED")
            return response.content, ".mp3"


class NullTTSProvider(TTSProvider):
    async def synthesize(self, text: str) -> tuple[bytes, str]:
        return b"", ".mp3"


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.ai_provider == "openai" and settings.openai_api_key:
        return OpenAIEmbedding(settings)
    if settings.openai_api_key:
        return OpenAIEmbedding(settings)
    return LocalHashEmbedding()


def build_chat_provider(settings: Settings) -> ChatProvider:
    provider = (settings.ai_provider or "groq").lower()
    if provider == "openai":
        if not settings.openai_api_key:
            log.warning("openai_key_missing_falling_back_to_mock")
            return MockChatProvider()
        return OpenAIChatProvider(settings)
    if provider == "mock":
        return MockChatProvider()
    if not settings.groq_api_key:
        log.warning("groq_key_missing_falling_back_to_mock")
        return MockChatProvider()
    return GroqChatProvider(settings)


def build_vision_provider(settings: Settings) -> VisionProvider:
    provider = (settings.ai_provider or "groq").lower()
    if provider == "openai":
        if not settings.openai_api_key:
            return MockVisionProvider()
        return OpenAIVisionProvider(settings)
    if provider == "mock":
        return MockVisionProvider()
    if not settings.groq_api_key:
        return MockVisionProvider()
    return GroqVisionProvider(settings)


def build_stt_provider(settings: Settings) -> STTProvider:
    provider = (settings.ai_provider or "groq").lower()
    if provider == "openai":
        if not settings.openai_api_key:
            return MockSTTProvider()
        return OpenAISTTProvider(settings)
    if provider == "mock":
        return MockSTTProvider()
    if not settings.groq_api_key:
        return MockSTTProvider()
    return GroqSTTProvider(settings)


def build_tts_provider(settings: Settings) -> TTSProvider:
    kind = (settings.ai_tts_provider or "edge").lower()
    if kind == "openai":
        return OpenAITTSProvider(settings)
    if kind in {"none", "off", "null"}:
        return NullTTSProvider()
    return EdgeTTSProvider(settings)


def provider_status(settings: Settings) -> dict[str, Any]:
    configured = False
    active = (settings.ai_provider or "groq").lower()
    if active == "mock":
        configured = True
    elif active == "openai":
        configured = bool(settings.openai_api_key)
    else:
        configured = bool(settings.groq_api_key)
    return {
        "provider": settings.ai_provider,
        "chatConfigured": configured,
        "usingMockFallback": active != "mock" and not configured,
        "ttsProvider": settings.ai_tts_provider,
        "embedding": "openai" if settings.openai_api_key else "local",
        "chatModel": (
            settings.openai_chat_model if settings.ai_provider == "openai" else settings.groq_chat_model
        ),
        "visionModel": (
            settings.openai_vision_model if settings.ai_provider == "openai" else settings.groq_vision_model
        ),
        "supportsImages": True,
    }
