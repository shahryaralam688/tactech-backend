"""Realtime ``workout.session.changed`` for the trainee's own trainer (live-session view).

Fire-and-forget and failure-proof: scheduled from the trainee routes as a FastAPI
background task (runs after the response and DB commit), never raises, never touches
the trainee response. Payload is ids + status only; the trainer app refetches
``GET /trainer/trainees/{id}/sessions/active`` for details. No inbox row, no push.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal
from app.realtime.chat_hub import chat_hub

log = get_logger("tactech.live_session")

ACTIONS = ("started", "set_logged", "completed", "discarded")


def _emit_sync(user_id: str, payload: dict[str, Any]) -> None:
    async def _go() -> None:
        await chat_hub.emit_workout_session_changed(user_id, payload)

    try:
        from anyio import from_thread

        from_thread.run(_go)
    except RuntimeError:
        asyncio.run(_go())


def notify_trainer_session_changed(trainee_id: str, session_id: str, status: str, action: str) -> None:
    """Tell the trainee's trainer (room ``user:{trainerUserId}``) that a session changed."""
    try:
        db = SessionLocal()
        try:
            trainer_user_id = db.scalar(
                select(models.TrainerProfile.user_id)
                .join(models.TraineeProfile, models.TraineeProfile.trainer_id == models.TrainerProfile.id)
                .where(models.TraineeProfile.id == trainee_id)
            )
        finally:
            db.close()
        if not trainer_user_id:
            return  # trainee has no trainer: nothing to emit
        _emit_sync(
            trainer_user_id,
            {
                "traineeId": trainee_id,
                "sessionId": session_id,
                "status": status,
                "action": action,
                "occurredAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception:
        log.exception("live_session_emit_failed", trainee_id=trainee_id, session_id=session_id, action=action)
