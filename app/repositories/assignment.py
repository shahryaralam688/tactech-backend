from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.db import models


class AssignmentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_for_trainee(self, trainee_id: str) -> models.PlanAssignment | None:
        stmt = (
            select(models.PlanAssignment)
            .options(
                joinedload(models.PlanAssignment.plan).joinedload(models.WorkoutPlan.exercises),
                joinedload(models.PlanAssignment.plan)
                .joinedload(models.WorkoutPlan.days)
                .joinedload(models.PlanDay.exercises)
                .joinedload(models.PlanExercise.prescribed_sets),
            )
            .where(models.PlanAssignment.trainee_id == trainee_id)
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def get(self, assignment_id: str) -> models.PlanAssignment | None:
        stmt = (
            select(models.PlanAssignment)
            .options(joinedload(models.PlanAssignment.plan), joinedload(models.PlanAssignment.trainee))
            .where(models.PlanAssignment.id == assignment_id)
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def get_by_plan_and_trainee(self, plan_id: str, trainee_id: str) -> models.PlanAssignment | None:
        stmt = select(models.PlanAssignment).where(
            models.PlanAssignment.plan_id == plan_id,
            models.PlanAssignment.trainee_id == trainee_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def replace(self, assignment: models.PlanAssignment) -> models.PlanAssignment:
        self.db.execute(
            delete(models.PlanAssignment).where(models.PlanAssignment.trainee_id == assignment.trainee_id)
        )
        self.db.add(assignment)
        self.db.flush()
        return assignment

    def delete(self, assignment: models.PlanAssignment) -> None:
        self.db.delete(assignment)
        self.db.flush()

    def list_for_plan(self, plan_id: str) -> list[models.PlanAssignment]:
        stmt = (
            select(models.PlanAssignment)
            .options(joinedload(models.PlanAssignment.trainee))
            .where(models.PlanAssignment.plan_id == plan_id)
        )
        return list(self.db.execute(stmt).unique().scalars().all())

    def clear_for_plan(self, plan_id: str) -> list[models.PlanAssignment]:
        """Delete all assignments for plan. Returns the rows that were cleared (for notify)."""
        rows = self.list_for_plan(plan_id)
        self.db.execute(delete(models.PlanAssignment).where(models.PlanAssignment.plan_id == plan_id))
        self.db.flush()
        return rows
