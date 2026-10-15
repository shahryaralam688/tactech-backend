"""Trainer ↔ trainee invite roster links."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class RosterLinkRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active_for_trainee(self, trainee_id: str) -> models.TrainerTraineeLink | None:
        return self.db.scalars(
            select(models.TrainerTraineeLink)
            .where(
                models.TrainerTraineeLink.trainee_id == trainee_id,
                models.TrainerTraineeLink.status == "active",
            )
            .limit(1)
        ).first()

    def get_active_pair(
        self, *, trainer_id: str, trainee_id: str
    ) -> models.TrainerTraineeLink | None:
        return self.db.scalars(
            select(models.TrainerTraineeLink)
            .where(
                models.TrainerTraineeLink.trainer_id == trainer_id,
                models.TrainerTraineeLink.trainee_id == trainee_id,
                models.TrainerTraineeLink.status == "active",
            )
            .limit(1)
        ).first()

    def add(self, row: models.TrainerTraineeLink) -> models.TrainerTraineeLink:
        self.db.add(row)
        self.db.flush()
        return row
