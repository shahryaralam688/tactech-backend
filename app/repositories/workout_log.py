from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import models


class WorkoutLogRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_trainee(self, trainee_id: str) -> list[models.WorkoutLog]:
        stmt = (
            select(models.WorkoutLog)
            .options(joinedload(models.WorkoutLog.sets))
            .where(models.WorkoutLog.trainee_id == trainee_id)
            .order_by(models.WorkoutLog.completed_at.desc())
        )
        return list(self.db.execute(stmt).unique().scalars().all())

    def add(self, log: models.WorkoutLog) -> models.WorkoutLog:
        self.db.add(log)
        self.db.flush()
        return log
