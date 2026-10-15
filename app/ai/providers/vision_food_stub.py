"""Food scan vision stub — returns AI_CAPABILITY_UNAVAILABLE until paid keys exist."""

from __future__ import annotations

from typing import Any

from app.ai.providers.base import VisionCapabilityProvider
from app.core.exceptions import AiCapabilityUnavailableError


class FoodVisionStub(VisionCapabilityProvider):
    name = "stub"
    capability = "visionFood"

    @property
    def is_live(self) -> bool:
        return False

    async def analyze(self, *, image_bytes: bytes, content_type: str | None, prompt: str) -> dict[str, Any]:
        raise AiCapabilityUnavailableError(
            "Food scan AI is not configured yet. Coming soon.",
            capability="visionFood",
            status_code=501,
        )
