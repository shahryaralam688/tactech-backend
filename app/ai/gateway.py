"""AI Gateway — factory for text + vision providers (env-swappable)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, AsyncIterator

from app.ai.providers.base import TextLLMProvider, VisionCapabilityProvider
from app.ai.providers.text_gemini import GeminiTextProvider
from app.ai.providers.text_groq import GroqTextProvider
from app.ai.providers.text_mock import MockTextProvider
from app.ai.providers.text_openai import OpenAITextProvider
from app.ai.providers.vision_food_stub import FoodVisionStub
from app.ai.providers.vision_pose_stub import PoseVisionStub
from app.core.config import Settings, get_settings
from app.core.exceptions import AiProviderNotConfiguredError
from app.core.logging import get_logger

log = get_logger("tactech.ai.gateway")


def resolve_text_provider_name(settings: Settings) -> str:
    """Return concrete provider id: gemini|groq|openai|mock|unconfigured."""
    requested = (settings.ai_text_provider or "auto").lower().strip()
    if requested == "auto":
        if (settings.gemini_api_key or "").strip():
            return "gemini"
        if (settings.groq_api_key or "").strip():
            return "groq"
        if (settings.openai_api_key or "").strip():
            return "openai"
        return "mock"
    if requested == "gemini":
        return "gemini" if (settings.gemini_api_key or "").strip() else "unconfigured"
    if requested == "groq":
        return "groq" if (settings.groq_api_key or "").strip() else "unconfigured"
    if requested == "openai":
        return "openai" if (settings.openai_api_key or "").strip() else "unconfigured"
    if requested == "mock":
        return "mock"
    return "unconfigured"


def build_text_provider(settings: Settings) -> TextLLMProvider:
    name = resolve_text_provider_name(settings)
    if name == "gemini":
        return GeminiTextProvider(settings)
    if name == "groq":
        return GroqTextProvider(settings)
    if name == "openai":
        return OpenAITextProvider(settings)
    if name == "mock":
        return MockTextProvider()
    raise AiProviderNotConfiguredError(
        f"AI text provider '{settings.ai_text_provider}' is not configured (missing API key)."
    )


def build_pose_provider(settings: Settings) -> VisionCapabilityProvider:
    kind = (settings.ai_vision_pose_provider or "stub").lower().strip()
    if kind in {"", "stub", "none", "off"}:
        return PoseVisionStub()
    # Future paid providers plug in here
    return PoseVisionStub()


def build_food_provider(settings: Settings) -> VisionCapabilityProvider:
    kind = (settings.ai_vision_food_provider or "stub").lower().strip()
    if kind in {"", "stub", "none", "off"}:
        return FoodVisionStub()
    return FoodVisionStub()


class _ChatProviderAdapter:
    """Adapt TextLLMProvider → legacy CoachService ChatProvider interface."""

    def __init__(self, inner: TextLLMProvider) -> None:
        self.inner = inner

    async def complete(self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int) -> str:
        return await self.inner.complete(messages, temperature=temperature, max_tokens=max_tokens)

    async def stream(
        self, messages: list[dict[str, Any]], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        async for chunk in self.inner.stream(messages, temperature=temperature, max_tokens=max_tokens):
            yield chunk


class AiGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.text = build_text_provider(settings)
        self.pose = build_pose_provider(settings)
        self.food = build_food_provider(settings)

    @property
    def text_provider_name(self) -> str:
        return resolve_text_provider_name(self.settings)

    def as_chat_provider(self) -> _ChatProviderAdapter:
        return _ChatProviderAdapter(self.text)

    async def complete_text(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_json: bool = False,
    ) -> str:
        return await self.text.complete(
            messages,
            temperature=temperature if temperature is not None else self.settings.ai_chat_temperature,
            max_tokens=max_tokens if max_tokens is not None else self.settings.ai_chat_max_tokens,
            response_json=response_json,
        )


@lru_cache
def get_ai_gateway() -> AiGateway:
    return AiGateway(get_settings())
