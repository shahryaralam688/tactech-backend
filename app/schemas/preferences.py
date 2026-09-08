from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel
from app.schemas.requests import RequestModel

LANGUAGE_LABELS = {
    "jp": "Japanese (JP)",
    "us": "English (US)",
    "uk": "English (UK)",
    "it": "Italian (IT)",
    "ar": "Arabic (AR)",
    "cn": "Chinese (CN)",
    "ru": "Russian (RU)",
}


class NotificationPreferences(APIModel):
    push: bool = True
    ai_coach: bool = False
    metrics: bool = True
    vibrations: bool = False
    sound: bool = True
    app_update: bool = True
    resources: bool = False
    offers_device: bool = False


class SecurityPreferences(APIModel):
    two_factor: bool = False
    google_auth: bool = False
    face_id: bool = True
    biometric: bool = True


class LanguagePreferences(APIModel):
    language_code: str = "us"
    language_label: str = "English (US)"
    bilingual: bool = False


class AppFeedbackRequest(RequestModel):
    areas: list[str] = Field(default_factory=list)
    message: str | None = None
    app_version: str | None = None
    platform: str | None = None


class AppFeedbackCreated(APIModel):
    id: str
    areas: list[str]
    created_at: datetime


class AppFeedbackOut(AppFeedbackCreated):
    message: str | None = None
    app_version: str | None = None
    platform: str | None = None
