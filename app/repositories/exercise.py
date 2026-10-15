from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models


class ExerciseRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, exercise_id: str) -> models.Exercise | None:
        return self.db.get(models.Exercise, exercise_id)

    def get_by_name(self, name: str) -> models.Exercise | None:
        stmt = select(models.Exercise).where(func.lower(models.Exercise.name) == name.strip().lower())
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(self, *, active_only: bool = True) -> list[models.Exercise]:
        stmt = select(models.Exercise)
        if active_only:
            stmt = stmt.where(models.Exercise.active.is_(True))
        stmt = stmt.order_by(models.Exercise.sort_order.asc(), models.Exercise.name.asc())
        return list(self.db.execute(stmt).scalars().all())

    def add(self, exercise: models.Exercise) -> models.Exercise:
        self.db.add(exercise)
        self.db.flush()
        return exercise

    def commit(self) -> None:
        self.db.commit()

    def flush(self) -> None:
        self.db.flush()
