from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class ExerciseRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, exercise_id: str) -> models.Exercise | None:
        return self.db.get(models.Exercise, exercise_id)

    def list_all(self) -> list[models.Exercise]:
        stmt = select(models.Exercise).order_by(models.Exercise.name)
        return list(self.db.execute(stmt).scalars().all())

    def add(self, exercise: models.Exercise) -> models.Exercise:
        self.db.add(exercise)
        self.db.flush()
        return exercise
