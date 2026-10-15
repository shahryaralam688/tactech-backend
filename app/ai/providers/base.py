"""Shared text / vision provider interfaces for the AI gateway."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class TextLLMProvider(ABC):
    """OpenAI-compatible message list in/out. Same interface for gemini/groq/openai."""

    name: str = "text"

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        response_json: bool = False,
    ) -> str:
        raise NotImplementedError

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        text = await self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        size = 24
        for i in range(0, len(text), size):
            yield text[i : i + size]


class VisionCapabilityProvider(ABC):
    """Pose / food vision. Stubs raise AI_CAPABILITY_UNAVAILABLE."""

    name: str = "vision"
    capability: str = "vision"

    @property
    def is_live(self) -> bool:
        return False

    @abstractmethod
    async def analyze(self, *, image_bytes: bytes, content_type: str | None, prompt: str) -> dict[str, Any]:
        raise NotImplementedError
