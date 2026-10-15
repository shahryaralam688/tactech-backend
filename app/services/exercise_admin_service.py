"""Admin ops for exercise catalog + Form Studio 3D metadata."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.storage import absolute_media_url, normalize_client_media_url, save_form3d_asset
from app.db import models
from app.repositories.exercise import ExerciseRepository
from app.schemas.common import ExerciseOut
from app.schemas.form3d_admin import ExerciseCreateRequest, Form3dUpdateRequest, Form3dUploadOut
from app.schemas.mappers import exercise_out


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExerciseAdminService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.exercises = ExerciseRepository(db)

    def update_form3d(self, exercise_id: str, payload: Form3dUpdateRequest) -> ExerciseOut:
        row = self.exercises.get(exercise_id)
        if row is None:
            raise NotFoundError("Exercise not found.")

        data = payload.model_dump(exclude_unset=True)
        if "enabled" in data and data["enabled"] is not None:
            row.form3d_enabled = bool(data["enabled"])
        if "clip_id" in data:
            row.form3d_clip_id = data["clip_id"]
        if "character" in data:
            row.form3d_character = data["character"] or "x_bot"
        if "animation_url" in data:
            url = normalize_client_media_url(self.settings, data["animation_url"])
            if data["animation_url"] and url is None:
                raise ValidationAppError(
                    "animationUrl must be https CDN or /uploads/ path.",
                    fields={"animationUrl": "invalid"},
                )
            row.form3d_animation_url = url
        if "cues" in data and data["cues"] is not None:
            row.form3d_cues = list(data["cues"])
        if "guide" in data and data["guide"] is not None:
            row.form3d_guide = [
                g.model_dump(by_alias=True, exclude_none=True) for g in (payload.guide or [])
            ]
        if "mixamo_query" in data:
            row.mixamo_query = data["mixamo_query"]

        if row.form3d_enabled:
            row.form3d_character = row.form3d_character or "x_bot"
            if not row.form3d_clip_id and not row.form3d_animation_url:
                raise ValidationAppError(
                    "Enable Form 3D only with clipId and/or animationUrl.",
                    fields={"form3d": "incomplete"},
                )

        row.updated_at = _utcnow()
        self.db.commit()
        self.db.refresh(row)
        return exercise_out(row)

    def create_exercise(self, payload: ExerciseCreateRequest) -> ExerciseOut:
        eid = payload.id.strip()
        if self.exercises.get(eid):
            raise ConflictError("An exercise with this id already exists.")
        form3d = payload.form3d
        row = models.Exercise(
            id=eid,
            name=payload.name.strip(),
            muscle_group=payload.muscle_group,
            equipment=payload.equipment,
            difficulty=payload.difficulty,
            cues=list(payload.cues or []),
            icon=payload.icon,
            category=payload.category,
            muscles=list(payload.muscles or []) or [payload.muscle_group],
            level=(payload.level or payload.difficulty).lower(),
            equipment_list=list(payload.equipment_list or [])
            or [payload.equipment.lower()],
            instructions=payload.instructions,
            common_mistakes=list(payload.common_mistakes or []),
            thumbnail_url=payload.thumbnail_url,
            mixamo_query=payload.mixamo_query,
            sort_order=payload.sort_order,
            form3d_enabled=bool(form3d.enabled) if form3d else False,
            form3d_clip_id=form3d.clip_id if form3d else None,
            form3d_character=(form3d.character or "x_bot") if form3d and form3d.enabled else None,
            form3d_animation_url=form3d.animation_url if form3d else None,
            form3d_guide=[g.model_dump(by_alias=True) for g in (form3d.guide if form3d else [])],
            form3d_cues=list(form3d.cues) if form3d else [],
            active=True,
            updated_at=_utcnow(),
        )
        self.exercises.add(row)
        self.db.commit()
        self.db.refresh(row)
        return exercise_out(row)

    def upload_form3d(
        self, *, filename: str, data: bytes, content_type: str | None
    ) -> Form3dUploadOut:
        stored, key, ctype = save_form3d_asset(
            self.settings,
            filename=filename,
            data=data,
            content_type=content_type,
        )
        abs_url = absolute_media_url(None, self.settings, stored) or stored
        if abs_url.startswith("/") and self.settings.public_base_url:
            abs_url = self.settings.public_base_url.rstrip("/") + abs_url
        return Form3dUploadOut(animation_url=abs_url, key=key, content_type=ctype)
