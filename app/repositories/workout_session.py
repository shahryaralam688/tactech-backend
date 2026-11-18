from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import models


class WorkoutSessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, session_id: str) -> models.WorkoutSession | None:
        stmt = (
            select(models.WorkoutSession)
            .options(joinedload(models.WorkoutSession.sets))
            .where(models.WorkoutSession.id == session_id)
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def get_active_for_trainee(self, trainee_id: str) -> models.WorkoutSession | None:
        stmt = (
            select(models.WorkoutSession)
            .options(joinedload(models.WorkoutSession.sets))
            .where(
                models.WorkoutSession.trainee_id == trainee_id,
                models.WorkoutSession.status == "active",
            )
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def get_newest_active_for_trainee(self, trainee_id: str) -> models.WorkoutSession | None:
        """Newest active row only (never raises on duplicate active rows). Trainer live view."""
        stmt = (
            select(models.WorkoutSession)
            .options(joinedload(models.WorkoutSession.sets))
            .where(
                models.WorkoutSession.trainee_id == trainee_id,
                models.WorkoutSession.status == "active",
            )
            .order_by(models.WorkoutSession.started_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).unique().scalars().first()

    def add(self, session: models.WorkoutSession) -> models.WorkoutSession:
        self.db.add(session)
        self.db.flush()
        return session

    def add_set(self, s: models.WorkoutSessionSet) -> models.WorkoutSessionSet:
        self.db.merge(s)
        self.db.flush()
        return s
