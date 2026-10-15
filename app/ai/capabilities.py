"""GET /coach/ai/capabilities payload builder."""

from __future__ import annotations

from app.ai.gateway import resolve_text_provider_name
from app.core.config import Settings
from app.schemas.common import APIModel


class AiCapabilitiesOut(APIModel):
    text_chat: bool = True
    structured_plan_json: bool = True
    weekly_summary: bool = True
    vision_pose: bool = False
    vision_food: bool = False
    text_provider: str
    vision_pose_provider: str
    vision_food_provider: str
    free_chat_daily_limit: int
    free_plan_generations: int


def build_capabilities(settings: Settings) -> AiCapabilitiesOut:
    text_name = resolve_text_provider_name(settings)
    pose = (settings.ai_vision_pose_provider or "stub").lower().strip()
    food = (settings.ai_vision_food_provider or "stub").lower().strip()
    text_live = text_name != "unconfigured"
    # Stubs are never live
    pose_live = pose not in {"", "stub", "none", "off"}
    food_live = food not in {"", "stub", "none", "off"}
    return AiCapabilitiesOut(
        text_chat=text_live,
        structured_plan_json=text_live,
        weekly_summary=text_live,
        vision_pose=pose_live,
        vision_food=food_live,
        text_provider=text_name if text_name != "unconfigured" else (settings.ai_text_provider or "auto"),
        vision_pose_provider=pose or "stub",
        vision_food_provider=food or "stub",
        free_chat_daily_limit=max(0, int(settings.ai_free_chat_daily_limit or 0)),
        free_plan_generations=max(0, int(settings.ai_free_plan_generations or 0)),
    )
