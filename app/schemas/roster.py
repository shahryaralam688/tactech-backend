"""Trainer ↔ trainee invite roster unlink / remove DTOs."""

from datetime import datetime

from app.schemas.common import APIModel


class UnlinkOut(APIModel):
    """Trainee leave response. iOS requires ok + endedAt; trainerUserId optional."""

    ok: bool = True
    ended_at: datetime
    trainer_user_id: str | None = None


class RemoveTraineeOut(APIModel):
    ok: bool = True
    trainee_id: str
    ended_at: datetime
