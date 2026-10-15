"""Join-request persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class JoinRequestRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, request_id: str) -> models.JoinRequest | None:
        return self.db.get(models.JoinRequest, request_id)

    def get_pending_for_trainee_user(self, trainee_user_id: str) -> models.JoinRequest | None:
        return self.db.scalars(
            select(models.JoinRequest)
            .where(
                models.JoinRequest.trainee_user_id == trainee_user_id,
                models.JoinRequest.status == "pending",
            )
            .limit(1)
        ).first()

    def list_for_trainer(
        self, trainer_user_id: str, *, status: str | None = "pending"
    ) -> list[models.JoinRequest]:
        stmt = select(models.JoinRequest).where(
            models.JoinRequest.trainer_user_id == trainer_user_id
        )
        if status and status != "all":
            stmt = stmt.where(models.JoinRequest.status == status)
        stmt = stmt.order_by(models.JoinRequest.created_at.desc())
        return list(self.db.scalars(stmt).all())

    def add(self, row: models.JoinRequest) -> models.JoinRequest:
        self.db.add(row)
        self.db.flush()
        return row

    def list_pending_for_trainee(self, trainee_user_id: str) -> list[models.JoinRequest]:
        return list(
            self.db.scalars(
                select(models.JoinRequest).where(
                    models.JoinRequest.trainee_user_id == trainee_user_id,
                    models.JoinRequest.status == "pending",
                )
            ).all()
        )
