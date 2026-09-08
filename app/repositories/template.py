from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import models


class TemplateRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, template_id: str) -> models.ExerciseTemplate | None:
        stmt = (
            select(models.ExerciseTemplate)
            .options(joinedload(models.ExerciseTemplate.set_rows))
            .where(models.ExerciseTemplate.id == template_id)
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def list_for_trainer(
        self,
        trainer_id: str,
        exercise_id: str | None = None,
    ) -> list[models.ExerciseTemplate]:
        stmt = (
            select(models.ExerciseTemplate)
            .options(joinedload(models.ExerciseTemplate.set_rows))
            .where(models.ExerciseTemplate.trainer_id == trainer_id)
        )
        if exercise_id:
            stmt = stmt.where(models.ExerciseTemplate.exercise_id == exercise_id)
        stmt = stmt.order_by(models.ExerciseTemplate.updated_at.desc())
        return list(self.db.execute(stmt).unique().scalars().all())

    def add(self, template: models.ExerciseTemplate) -> models.ExerciseTemplate:
        self.db.add(template)
        self.db.flush()
        return template

    def delete(self, template: models.ExerciseTemplate) -> None:
        self.db.delete(template)
        self.db.flush()
