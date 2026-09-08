from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.db import models
from app.repositories.exercise import ExerciseRepository
from app.repositories.template import TemplateRepository
from app.schemas.templates import (
    ExerciseTemplateIn,
    ExerciseTemplateOut,
    TemplateSetRowOut,
    UpdateExerciseTemplateRequest,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def template_out(template: models.ExerciseTemplate) -> ExerciseTemplateOut:
    return ExerciseTemplateOut(
        id=template.id,
        exercise_id=template.exercise_id,
        trainer_id=template.trainer_id,
        name=template.name,
        sets=template.sets,
        reps=template.reps,
        rest_seconds=template.rest_seconds,
        weight_kg=template.weight_kg,
        tempo=template.tempo,
        rpe=template.rpe,
        how_to=template.how_to,
        side=template.side,
        set_rows=[
            TemplateSetRowOut(
                id=row.id,
                set_number=row.set_number,
                reps=row.reps,
                weight_kg=row.weight_kg,
            )
            for row in sorted(template.set_rows, key=lambda item: item.set_number)
        ],
        updated_at=template.updated_at,
    )


class TemplateService:
    def __init__(self, db: Session) -> None:
        self.templates = TemplateRepository(db)
        self.exercises = ExerciseRepository(db)

    def list_templates(self, trainer_id: str, exercise_id: str | None) -> list[ExerciseTemplateOut]:
        return [template_out(item) for item in self.templates.list_for_trainer(trainer_id, exercise_id)]

    def create(self, trainer_id: str, payload: ExerciseTemplateIn) -> ExerciseTemplateOut:
        if self.exercises.get(payload.exercise_id) is None:
            raise ValidationAppError("Unknown exercise.")
        name = payload.name.strip()
        if not name:
            raise ValidationAppError("Enter a template name.")
        template_id = payload.id or str(uuid4())
        if self.templates.get(template_id):
            raise ConflictError("A template with this id already exists.")
        now = _utc_now()
        template = models.ExerciseTemplate(
            id=template_id,
            exercise_id=payload.exercise_id,
            trainer_id=trainer_id,
            name=name,
            sets=payload.sets,
            reps=payload.reps,
            rest_seconds=payload.rest_seconds,
            weight_kg=payload.weight_kg,
            tempo=payload.tempo,
            rpe=payload.rpe,
            how_to=payload.how_to,
            side=payload.side,
            created_at=now,
            updated_at=now,
            set_rows=self._rows(payload.set_rows),
        )
        return template_out(self.templates.add(template))

    def update(self, trainer_id: str, template_id: str, payload: UpdateExerciseTemplateRequest) -> ExerciseTemplateOut:
        template = self._owned(trainer_id, template_id)
        if payload.exercise_id is not None:
            if self.exercises.get(payload.exercise_id) is None:
                raise ValidationAppError("Unknown exercise.")
            template.exercise_id = payload.exercise_id
        if payload.name is not None:
            name = payload.name.strip()
            if not name:
                raise ValidationAppError("Enter a template name.")
            template.name = name
        if payload.sets is not None:
            template.sets = payload.sets
        if payload.reps is not None:
            template.reps = payload.reps
        if payload.rest_seconds is not None:
            template.rest_seconds = payload.rest_seconds
        if payload.weight_kg is not None:
            template.weight_kg = payload.weight_kg
        if payload.tempo is not None:
            template.tempo = payload.tempo
        if payload.rpe is not None:
            template.rpe = payload.rpe
        if payload.how_to is not None:
            template.how_to = payload.how_to
        if payload.side is not None:
            template.side = payload.side
        if payload.set_rows is not None:
            template.set_rows.clear()
            template.set_rows = self._rows(payload.set_rows)
        template.updated_at = _utc_now()
        return template_out(template)

    def delete(self, trainer_id: str, template_id: str) -> None:
        template = self._owned(trainer_id, template_id)
        self.templates.delete(template)

    def _owned(self, trainer_id: str, template_id: str) -> models.ExerciseTemplate:
        template = self.templates.get(template_id)
        if template is None:
            raise NotFoundError("Exercise template not found.")
        if template.trainer_id != trainer_id:
            raise ForbiddenError("You can only change your own templates.")
        return template

    def _rows(self, rows) -> list[models.ExerciseTemplateSetRow]:
        return [
            models.ExerciseTemplateSetRow(
                id=row.id or str(uuid4()),
                set_number=row.set_number,
                reps=row.reps,
                weight_kg=row.weight_kg,
            )
            for row in rows
        ]
