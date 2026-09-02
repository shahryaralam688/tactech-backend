from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import models

PLAN_LOAD_OPTIONS = (
    joinedload(models.WorkoutPlan.exercises),
    joinedload(models.WorkoutPlan.days)
    .joinedload(models.PlanDay.exercises)
    .joinedload(models.PlanExercise.prescribed_sets),
)


class PlanRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, plan_id: str) -> models.WorkoutPlan | None:
        stmt = (
            select(models.WorkoutPlan)
            .options(*PLAN_LOAD_OPTIONS)
            .where(models.WorkoutPlan.id == plan_id)
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def list_for_trainer(self, trainer_id: str) -> list[models.WorkoutPlan]:
        stmt = (
            select(models.WorkoutPlan)
            .options(*PLAN_LOAD_OPTIONS)
            .where(models.WorkoutPlan.trainer_id == trainer_id)
            .order_by(models.WorkoutPlan.title)
        )
        return list(self.db.execute(stmt).unique().scalars().all())

    def add(self, plan: models.WorkoutPlan) -> models.WorkoutPlan:
        self.db.add(plan)
        self.db.flush()
        return plan
