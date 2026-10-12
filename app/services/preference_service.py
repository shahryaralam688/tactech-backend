from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db import models
from app.repositories.app_feedback import AppFeedbackRepository
from app.repositories.preference import PreferenceRepository
from app.schemas.preferences import (
    LANGUAGE_LABELS,
    AppFeedbackCreated,
    AppFeedbackOut,
    AppFeedbackRequest,
    LanguagePreferences,
    NotificationPreferences,
    SecurityPreferences,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_notifications() -> dict:
    return NotificationPreferences().model_dump(by_alias=True)


def default_security() -> dict:
    return SecurityPreferences().model_dump(by_alias=True)


def default_language() -> dict:
    return LanguagePreferences().model_dump(by_alias=True)


class PreferenceService:
    def __init__(self, db: Session) -> None:
        self.prefs = PreferenceRepository(db)
        self.feedback = AppFeedbackRepository(db)

    def notifications(self, user_id: str) -> NotificationPreferences:
        row = self._ensure(user_id)
        merged = {**default_notifications(), **(row.notifications or {})}
        return NotificationPreferences.model_validate(merged)

    def save_notifications(self, user_id: str, payload: NotificationPreferences) -> NotificationPreferences:
        row = self._ensure(user_id)
        # Always persist full object with defaults so all 10 keys survive round-trips.
        merged = {**default_notifications(), **payload.model_dump(by_alias=True)}
        saved = NotificationPreferences.model_validate(merged)
        row.notifications = saved.model_dump(by_alias=True)
        row.updated_at = _utc_now()
        return saved

    def security(self, user_id: str) -> SecurityPreferences:
        return SecurityPreferences.model_validate(self._ensure(user_id).security)

    def save_security(self, user_id: str, payload: SecurityPreferences) -> SecurityPreferences:
        row = self._ensure(user_id)
        row.security = payload.model_dump(by_alias=True)
        row.updated_at = _utc_now()
        return SecurityPreferences.model_validate(row.security)

    def language(self, user_id: str) -> LanguagePreferences:
        return LanguagePreferences.model_validate(self._ensure(user_id).language)

    def save_language(self, user_id: str, payload: LanguagePreferences) -> LanguagePreferences:
        code = payload.language_code.strip().lower()
        label = payload.language_label.strip() or LANGUAGE_LABELS.get(code, payload.language_label)
        if code in LANGUAGE_LABELS and not payload.language_label.strip():
            label = LANGUAGE_LABELS[code]
        row = self._ensure(user_id)
        saved = LanguagePreferences(language_code=code, language_label=label, bilingual=payload.bilingual)
        row.language = saved.model_dump(by_alias=True)
        row.updated_at = _utc_now()
        return saved

    def submit_feedback(self, user_id: str, payload: AppFeedbackRequest) -> AppFeedbackCreated:
        item = models.AppFeedback(
            id=str(uuid4()),
            user_id=user_id,
            areas=payload.areas,
            message=payload.message.strip() if payload.message else None,
            app_version=payload.app_version,
            platform=payload.platform,
            created_at=_utc_now(),
        )
        saved = self.feedback.add(item)
        return AppFeedbackCreated(id=saved.id, areas=list(saved.areas), created_at=saved.created_at)

    def list_feedback(self, user_id: str) -> list[AppFeedbackOut]:
        return [
            AppFeedbackOut(
                id=item.id,
                areas=list(item.areas),
                created_at=item.created_at,
                message=item.message,
                app_version=item.app_version,
                platform=item.platform,
            )
            for item in self.feedback.list_for_user(user_id)
        ]

    def _ensure(self, user_id: str) -> models.UserPreferences:
        row = self.prefs.get(user_id)
        if row is not None:
            return row
        return self.prefs.add(
            models.UserPreferences(
                user_id=user_id,
                notifications=default_notifications(),
                security=default_security(),
                language=default_language(),
                updated_at=_utc_now(),
            )
        )
