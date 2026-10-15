"""Shared activate / soft-end for trainer–trainee invite roster links."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db import models
from app.repositories.assignment import AssignmentRepository
from app.repositories.roster_link import RosterLinkRepository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RosterLinkService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.links = RosterLinkRepository(db)
        self.assignments = AssignmentRepository(db)

    def activate(
        self,
        *,
        trainer: models.TrainerProfile,
        trainee: models.TraineeProfile,
        invite_code_used: str | None = None,
        source: str = "invite",
    ) -> models.TrainerTraineeLink:
        """Set active roster pointer + durable link row. Caller enforces 409 rules."""
        existing = self.links.get_active_for_trainee(trainee.id)
        if existing is not None and existing.trainer_id == trainer.id:
            trainee.trainer_id = trainer.id
            self.db.add(trainee)
            return existing

        if existing is not None:
            # Should not reach here — callers raise Conflict first.
            self._end_row(existing, ended_by_user_id=trainee.user_id)

        now = _utcnow()
        row = models.TrainerTraineeLink(
            id=str(uuid4()),
            trainer_id=trainer.id,
            trainee_id=trainee.id,
            trainer_user_id=trainer.user_id,
            trainee_user_id=trainee.user_id,
            status="active",
            invite_code_used=(invite_code_used or "").strip() or None,
            source=source,
            created_at=now,
            ended_at=None,
            ended_by_user_id=None,
        )
        self.links.add(row)
        trainee.trainer_id = trainer.id
        self.db.add(trainee)
        self.db.flush()
        return row

    def end_active(
        self,
        *,
        trainee: models.TraineeProfile,
        ended_by_user_id: str,
        expected_trainer_id: str | None = None,
    ) -> models.TrainerTraineeLink | None:
        """Soft-end active link, clear trainer_id + plan assignment. Chat untouched.

        Returns the ended link row, or None if there was no active link.
        """
        row = self.links.get_active_for_trainee(trainee.id)
        if row is None:
            # Heal denormalized pointer if orphaned
            if trainee.trainer_id and (
                expected_trainer_id is None or trainee.trainer_id == expected_trainer_id
            ):
                self._clear_assignment(trainee.id)
                trainee.trainer_id = None
                self.db.add(trainee)
                self.db.flush()
            return None

        if expected_trainer_id is not None and row.trainer_id != expected_trainer_id:
            return None

        self._end_row(row, ended_by_user_id=ended_by_user_id)
        self._clear_assignment(trainee.id)
        trainee.trainer_id = None
        self.db.add(trainee)
        self.db.flush()
        return row

    def _end_row(self, row: models.TrainerTraineeLink, *, ended_by_user_id: str) -> None:
        now = _utcnow()
        row.status = "ended"
        row.ended_at = now
        row.ended_by_user_id = ended_by_user_id
        self.db.add(row)
        self.db.flush()

    def _clear_assignment(self, trainee_id: str) -> None:
        assignment = self.assignments.get_for_trainee(trainee_id)
        if assignment is not None:
            self.assignments.delete(assignment)
