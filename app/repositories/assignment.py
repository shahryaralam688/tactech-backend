from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.db import models


class AssignmentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_for_trainee(self, trainee_id: str) -> models.PlanAssignment | None:
        stmt = (
            select(models.PlanAssignment)
            .options(joinedload(models.PlanAssignment.plan).joinedload(models.WorkoutPlan.exercises))
            .where(models.PlanAssignment.trainee_id == trainee_id)
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def replace(self, assignment: models.PlanAssignment) -> models.PlanAssignment:
        self.db.execute(
            delete(models.PlanAssignment).where(models.PlanAssignment.trainee_id == assignment.trainee_id)
        )
        self.db.add(assignment)
        self.db.flush()
        return assignment
