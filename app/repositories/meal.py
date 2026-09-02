from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class MealRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_trainee(self, trainee_id: str, on: date | None = None) -> list[models.Meal]:
        stmt = select(models.Meal).where(models.Meal.trainee_id == trainee_id)
        if on is not None:
            start = datetime.combine(on, time.min, tzinfo=timezone.utc)
            end = datetime.combine(on, time.max, tzinfo=timezone.utc)
            stmt = stmt.where(models.Meal.eaten_at >= start, models.Meal.eaten_at <= end)
        stmt = stmt.order_by(models.Meal.eaten_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def add(self, meal: models.Meal) -> models.Meal:
        self.db.add(meal)
        self.db.flush()
        return meal
