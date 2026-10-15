"""Invite → pending join request → trainer accept/reject."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.realtime.chat_hub import chat_hub
from app.repositories.join_request import JoinRequestRepository
from app.repositories.roster_link import RosterLinkRepository
from app.repositories.trainee import TraineeRepository
from app.repositories.trainer import TrainerRepository
from app.repositories.user import UserRepository
from app.schemas.join_requests import (
    ActiveLinkOut,
    JoinPartyOut,
    JoinRequestCreate,
    JoinRequestOut,
    JoinRequestStatusOut,
    RejectJoinRequest,
    TraineeJoinStateOut,
)
from app.schemas.mappers import user_public
from app.services.push_service import PushService
from app.services.roster_link_service import RosterLinkService

log = get_logger("tactech.join_requests")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JoinRequestService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.requests = JoinRequestRepository(db)
        self.trainees = TraineeRepository(db)
        self.trainers = TrainerRepository(db)
        self.users = UserRepository(db)
        self.roster = RosterLinkService(db)
        self.links = RosterLinkRepository(db)
        self.push = PushService(db, hub=chat_hub)

    # --- Trainee ------------------------------------------------------------

    def create(
        self, *, trainee_id: str, trainee_user_id: str, payload: JoinRequestCreate
    ) -> JoinRequestOut:
        trainee = self.trainees.get_with_user(trainee_id)
        if trainee is None:
            raise ForbiddenError("Trainee access required.")

        if trainee.trainer_id:
            raise ConflictError(
                "You already have a trainer. Leave them first.",
                code="ALREADY_LINKED",
            )
        if self.requests.get_pending_for_trainee_user(trainee_user_id):
            raise ConflictError(
                "You already have a pending request. Cancel it first.",
                code="PENDING_EXISTS",
            )

        code = payload.invite_code
        if not code:
            raise ValidationAppError(
                "Enter an invite code.",
                fields={"inviteCode": "required"},
            )
        trainer = self.trainers.get_by_invite_code(code)
        if trainer is None:
            raise NotFoundError("Invite code not found.", code="INVITE_NOT_FOUND")
        trainer_user = self.users.get(trainer.user_id)
        if trainer_user is None:
            raise NotFoundError("Invite code not found.", code="INVITE_NOT_FOUND")

        now = _utcnow()
        row = models.JoinRequest(
            id=f"jr_{uuid4().hex[:16]}",
            trainee_user_id=trainee_user_id,
            trainer_user_id=trainer.user_id,
            trainee_id=trainee.id,
            trainer_id=trainer.id,
            invite_code=code,
            message=payload.message,
            status="pending",
            created_at=now,
            updated_at=now,
            resolved_at=None,
        )
        self.requests.add(row)
        self.db.flush()

        trainee_name = trainee.user.name if trainee.user else "A trainee"
        # Durable trainer inbox + Socket user:{trainerUserId} — must not be dropped.
        # commit=True so trainer GET /me/notifications and list see the row immediately.
        notif = self.push.notify_inbox_sync(
            recipient_user_id=trainer.user_id,
            notif_type="join_request",
            title="New trainee request",
            body=f"{trainee_name} wants to join with your invite code.",
            data={
                "type": "join_request",
                "joinRequestId": row.id,
                "traineeUserId": trainee_user_id,
                "traineeName": trainee_name,
            },
            commit=True,
        )
        log.info(
            "join_request_created",
            join_request_id=row.id,
            trainee_user_id=trainee_user_id,
            trainer_user_id=trainer.user_id,
            notification_id=notif.id,
        )
        return self._out_for_trainee(row, trainer_user)

    def mine(self, *, trainee_id: str, trainee_user_id: str) -> TraineeJoinStateOut:
        trainee = self.trainees.get(trainee_id)
        if trainee is None:
            raise ForbiddenError("Trainee access required.")

        active_link: ActiveLinkOut | None = None
        if trainee.trainer_id:
            trainer = self.trainers.get_with_user(trainee.trainer_id)
            if trainer is not None and trainer.user is not None:
                link = self.links.get_active_for_trainee(trainee.id)
                active_link = ActiveLinkOut(
                    trainer_id=trainer.user_id,
                    trainer=self._party(trainer.user),
                    linked_at=link.created_at if link else None,
                )

        pending = self.requests.get_pending_for_trainee_user(trainee_user_id)
        pending_out = None
        if pending is not None:
            trainer_user = self.users.get(pending.trainer_user_id)
            pending_out = self._out_for_trainee(pending, trainer_user)

        return TraineeJoinStateOut(active_link=active_link, pending_request=pending_out)

    def cancel(self, *, trainee_user_id: str, request_id: str) -> JoinRequestStatusOut:
        row = self.requests.get(request_id)
        if row is None:
            raise NotFoundError("Join request not found.")
        if row.trainee_user_id != trainee_user_id:
            raise ForbiddenError("You can only cancel your own request.")
        if row.status != "pending":
            raise ValidationAppError(
                "Only pending requests can be cancelled.",
                fields={"status": "invalid"},
            )
        now = _utcnow()
        row.status = "cancelled"
        row.updated_at = now
        row.resolved_at = now
        self.db.add(row)
        self.db.flush()
        log.info("join_request_cancelled", join_request_id=row.id, user_id=trainee_user_id)
        return JoinRequestStatusOut(id=row.id, status=row.status)

    # --- Trainer ------------------------------------------------------------

    def list_for_trainer(
        self, *, trainer_user_id: str, status: str = "pending"
    ) -> list[JoinRequestOut]:
        status_n = (status or "pending").strip().lower()
        if status_n not in {"pending", "accepted", "rejected", "cancelled", "all"}:
            raise ValidationAppError(
                "status must be pending, accepted, rejected, cancelled, or all.",
                fields={"status": "invalid"},
            )
        rows = self.requests.list_for_trainer(trainer_user_id, status=status_n)
        out: list[JoinRequestOut] = []
        for row in rows:
            trainee_user = self.users.get(row.trainee_user_id)
            out.append(self._out_for_trainer(row, trainee_user))
        return out

    def accept(self, *, trainer_id: str, trainer_user_id: str, request_id: str) -> JoinRequestOut:
        row = self.requests.get(request_id)
        if row is None:
            raise NotFoundError("Join request not found.")
        if row.trainer_user_id != trainer_user_id or row.trainer_id != trainer_id:
            raise ForbiddenError("You can only accept requests sent to you.")
        if row.status != "pending":
            raise ValidationAppError(
                "Only pending requests can be accepted.",
                fields={"status": "invalid"},
            )

        trainee = self.trainees.get_with_user(row.trainee_id)
        trainer = self.trainers.get_with_user(trainer_id)
        if trainee is None or trainer is None:
            raise NotFoundError("Trainee or trainer profile not found.")

        if trainee.trainer_id and trainee.trainer_id != trainer.id:
            raise ConflictError(
                "This trainee is already linked to another coach.",
                code="ALREADY_LINKED",
            )

        now = _utcnow()
        row.status = "accepted"
        row.updated_at = now
        row.resolved_at = now
        self.db.add(row)

        # Cancel any other pending (defensive)
        for other in self.requests.list_pending_for_trainee(row.trainee_user_id):
            if other.id == row.id:
                continue
            other.status = "cancelled"
            other.updated_at = now
            other.resolved_at = now
            self.db.add(other)

        self.roster.activate(
            trainer=trainer,
            trainee=trainee,
            invite_code_used=row.invite_code,
            source="join_request",
        )
        self.db.flush()

        trainer_name = trainer.user.name if trainer.user else "Your trainer"
        # Durable trainee inbox + Socket user:{traineeUserId} (must not be dropped)
        notif = self.push.notify_inbox_sync(
            recipient_user_id=row.trainee_user_id,
            notif_type="join_request_accepted",
            title="Request accepted",
            body=f"{trainer_name} accepted your join request.",
            data={
                "type": "join_request_accepted",
                "joinRequestId": row.id,
                "trainerUserId": trainer_user_id,
                "trainerName": trainer_name,
            },
            commit=True,
        )

        try:
            self.push.emit_relationship_changed_sync(
                user_ids=[row.trainee_user_id, trainer_user_id],
                action="linked",
                reason="join_accepted",
                trainer_user_id=trainer_user_id,
                trainee_user_id=row.trainee_user_id,
                trainee_profile_id=row.trainee_id,
                occurred_at=now.isoformat().replace("+00:00", "Z"),
            )
        except Exception:
            log.exception(
                "join_accepted_relationship_emit_failed",
                join_request_id=row.id,
            )

        log.info(
            "join_request_accepted",
            join_request_id=row.id,
            trainer_user_id=trainer_user_id,
            trainee_user_id=row.trainee_user_id,
            notification_id=notif.id,
        )
        return self._out_for_trainer(row, trainee.user)

    def reject(
        self,
        *,
        trainer_id: str,
        trainer_user_id: str,
        request_id: str,
        payload: RejectJoinRequest | None = None,
    ) -> JoinRequestStatusOut:
        row = self.requests.get(request_id)
        if row is None:
            raise NotFoundError("Join request not found.")
        if row.trainer_user_id != trainer_user_id or row.trainer_id != trainer_id:
            raise ForbiddenError("You can only reject requests sent to you.")
        if row.status != "pending":
            raise ValidationAppError(
                "Only pending requests can be rejected.",
                fields={"status": "invalid"},
            )

        now = _utcnow()
        row.status = "rejected"
        row.updated_at = now
        row.resolved_at = now
        if payload and payload.reason:
            row.reject_reason = payload.reason
        self.db.add(row)
        self.db.flush()

        trainer = self.trainers.get_with_user(trainer_id)
        trainer_name = (
            trainer.user.name if trainer and trainer.user else "Your trainer"
        )
        # Durable trainee inbox + Socket — Pending UI must clear from this signal
        notif = self.push.notify_inbox_sync(
            recipient_user_id=row.trainee_user_id,
            notif_type="join_request_rejected",
            title="Request declined",
            body=f"{trainer_name} declined your join request.",
            data={
                "type": "join_request_rejected",
                "joinRequestId": row.id,
                "trainerUserId": trainer_user_id,
                "trainerName": trainer_name,
            },
            commit=True,
        )
        log.info(
            "join_request_rejected",
            join_request_id=row.id,
            trainer_user_id=trainer_user_id,
            trainee_user_id=row.trainee_user_id,
            notification_id=notif.id,
        )
        return JoinRequestStatusOut(id=row.id, status=row.status)

    # --- Helpers ------------------------------------------------------------

    def _party(self, user: models.User, *, include_email: bool = False) -> JoinPartyOut:
        pub = user_public(user, settings=self.settings)
        return JoinPartyOut(
            id=user.id,
            name=user.name,
            avatar_url=pub.avatar_url,
            email=user.email if include_email else None,
        )

    def _out_for_trainee(
        self, row: models.JoinRequest, trainer_user: models.User | None
    ) -> JoinRequestOut:
        return JoinRequestOut(
            id=row.id,
            status=row.status,
            invite_code=row.invite_code,
            message=row.message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            resolved_at=row.resolved_at,
            trainer=self._party(trainer_user) if trainer_user else None,
            trainee=None,
        )

    def _out_for_trainer(
        self, row: models.JoinRequest, trainee_user: models.User | None
    ) -> JoinRequestOut:
        return JoinRequestOut(
            id=row.id,
            status=row.status,
            invite_code=row.invite_code,
            message=row.message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            resolved_at=row.resolved_at,
            trainer=None,
            trainee=self._party(trainee_user, include_email=True) if trainee_user else None,
        )
