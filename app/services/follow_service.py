"""Free marketplace follow / hire (Phase 9).

Accept upserts TraineeProfile.trainer_id — same roster link as invite-code.
Contact / package inquire remain independent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.realtime.chat_hub import chat_hub
from app.repositories.chat import ChatRepository
from app.repositories.coach_profile import CoachProfileRepository
from app.schemas.follows import (
    CoachFollowOut,
    FollowCreateRequest,
    FollowStateOut,
    TrainerFollowItemOut,
    TrainerFollowPage,
)
from app.services.package_service import format_price_label
from app.services.push_service import PushService

if TYPE_CHECKING:
    from fastapi import Request

    from app.api.deps import Principal
    from app.core.config import Settings

log = get_logger("tactech.follows")

OPEN_STATUSES = frozenset({"pending", "active"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FollowService:
    def __init__(self, db: Session, settings: "Settings | None" = None) -> None:
        self.db = db
        self.settings = settings
        self.profiles = CoachProfileRepository(db)
        self.chat = ChatRepository(db)
        self.push = PushService(db, hub=chat_hub)

    # --- Trainee ------------------------------------------------------------

    def create_follow(
        self,
        principal: Principal,
        coach_profile_id: str,
        payload: FollowCreateRequest | None,
        *,
        request: "Request | None" = None,
    ) -> tuple[CoachFollowOut, int]:
        """Returns (follow, http_status). 200 = reuse/auto-accept; 201 = new pending."""
        self._require_trainee(principal)
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None or not profile.is_public:
            raise NotFoundError("Coach not available.")
        if principal.user_id == profile.user_id:
            raise ValidationAppError(
                "You cannot follow yourself.",
                fields={"coachProfileId": "self"},
            )

        trainee = self.db.get(models.TraineeProfile, principal.trainee_id)
        if trainee is None:
            raise ForbiddenError("Trainee access required.")

        # Already roster-linked to this coach
        if trainee.trainer_id == profile.trainer_id:
            raise ConflictError(
                "You are already linked to this coach.",
                fields={"follow": "already_linked"},
                code="ALREADY_LINKED",
            )

        # Existing open follow for this pair → return it (idempotent)
        existing_pair = self._open_for_pair(profile.id, principal.user_id)
        if existing_pair is not None:
            return self._to_out(existing_pair), 200

        # Open follow / link with another coach
        other_open = self._open_for_trainee(principal.user_id)
        if other_open is not None:
            raise ConflictError(
                "You already have a pending or active coach relationship. End it before following someone else.",
                fields={"follow": "other_open"},
            )
        if trainee.trainer_id and trainee.trainer_id != profile.trainer_id:
            raise ConflictError(
                "You are already linked to another coach. End that relationship first.",
                fields={"follow": "other_linked"},
            )

        note = ((payload.note if payload else None) or "").strip() or None
        if note and len(note) > 500:
            raise ValidationAppError("Note must be at most 500 characters.", fields={"note": "too_long"})

        package_id = None
        package_title = None
        price_label = None
        raw_pkg = (payload.package_id if payload else None) or None
        if raw_pkg:
            pkg = self.db.get(models.CoachPackage, raw_pkg)
            if (
                pkg is None
                or pkg.coach_profile_id != profile.id
                or pkg.status != "active"
            ):
                raise ValidationAppError(
                    "Package is not available for this coach.",
                    fields={"packageId": "invalid"},
                )
            package_id = pkg.id
            package_title = pkg.title
            price_label = format_price_label(
                amount_minor=pkg.amount_minor,
                currency=pkg.currency,
                billing_period=pkg.billing_period,
            )

        # Chat thread
        thread = self.chat.find_thread(profile.user_id, principal.user_id)
        if thread is None:
            thread = self.chat.create_thread(profile.user_id, principal.user_id)

        auto = (profile.follow_mode or "manual").lower() == "auto_accept"
        now = _utcnow()
        status = "active" if auto else "pending"
        row = models.CoachFollow(
            id=str(uuid4()),
            coach_profile_id=profile.id,
            trainer_user_id=profile.user_id,
            trainee_user_id=principal.user_id,
            status=status,
            package_id=package_id,
            package_title=package_title,
            note=note,
            thread_id=thread.id,
            created_at=now,
            updated_at=now,
            accepted_at=now if auto else None,
            ended_at=None,
            ended_by_user_id=None,
        )
        self.db.add(row)
        self.db.flush()

        # Chat context message
        parts = ["I'd like to follow you as my coach."]
        if package_title:
            label = f'"{package_title}"'
            if price_label:
                label = f"{label} ({price_label})"
            parts.append(f"Package: {label}")
        if note:
            parts.append(note)
        text = "\n\n".join(parts)[:4000]
        self.chat.add_message(
            thread,
            sender_user_id=principal.user_id,
            sender_role="trainee",
            kind="text",
            text=text,
            bump_unread=True,
        )

        if auto:
            self._link_roster(trainee, profile.trainer_id)
            self._analytics_event(profile, principal.user_id, "follow_accepted")
        else:
            self._analytics_event(profile, principal.user_id, "follow_requested")

        self.db.commit()
        self.db.refresh(row)

        if auto:
            self._notify(
                profile.user_id,
                notif_type="coach_follow",
                title="New trainee",
                body="A trainee started following you.",
                data={
                    "type": "coach_follow",
                    "followId": row.id,
                    "coachProfileId": profile.id,
                    "traineeUserId": principal.user_id,
                },
            )
            self._notify(
                principal.user_id,
                notif_type="coach_follow_accepted",
                title="You're linked",
                body="You're now linked with your coach.",
                data={
                    "type": "coach_follow_accepted",
                    "followId": row.id,
                    "coachProfileId": profile.id,
                },
            )
        else:
            self._notify(
                profile.user_id,
                notif_type="coach_follow",
                title="New follow request",
                body="A trainee wants to follow you as their coach.",
                data={
                    "type": "coach_follow",
                    "followId": row.id,
                    "coachProfileId": profile.id,
                    "traineeUserId": principal.user_id,
                },
            )

        log.info(
            "coach_follow_created",
            follow_id=row.id,
            coach_profile_id=profile.id,
            trainee_user_id=principal.user_id,
            status=row.status,
        )
        return self._to_out(row), (200 if auto else 201)

    def get_follow_state(
        self, principal: Principal, coach_profile_id: str
    ) -> FollowStateOut:
        self._require_trainee(principal)
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach not found.")

        trainee = self.db.get(models.TraineeProfile, principal.trainee_id)
        open_row = self._open_for_pair(profile.id, principal.user_id)
        if open_row is not None:
            return FollowStateOut(status=open_row.status, follow=self._to_out(open_row))

        # Roster-linked via invite without a follow row
        if trainee and trainee.trainer_id == profile.trainer_id:
            return FollowStateOut(status="active", follow=None)

        latest = self.db.scalars(
            select(models.CoachFollow)
            .where(
                models.CoachFollow.coach_profile_id == profile.id,
                models.CoachFollow.trainee_user_id == principal.user_id,
            )
            .order_by(models.CoachFollow.created_at.desc())
        ).first()
        if latest is not None:
            return FollowStateOut(status=latest.status, follow=self._to_out(latest))
        return FollowStateOut(status="none", follow=None)

    def cancel_pending(self, principal: Principal, coach_profile_id: str) -> CoachFollowOut:
        self._require_trainee(principal)
        row = self._open_for_pair(coach_profile_id, principal.user_id)
        if row is None or row.status != "pending":
            raise ValidationAppError(
                "No pending follow request to cancel.",
                fields={"follow": "not_pending"},
            )
        now = _utcnow()
        row.status = "ended"
        row.ended_at = now
        row.ended_by_user_id = principal.user_id
        row.updated_at = now
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        log.info("coach_follow_canceled", follow_id=row.id, trainee_user_id=principal.user_id)
        return self._to_out(row)

    def end_mine(self, principal: Principal) -> CoachFollowOut:
        self._require_trainee(principal)
        row = self.db.scalars(
            select(models.CoachFollow).where(
                models.CoachFollow.trainee_user_id == principal.user_id,
                models.CoachFollow.status == "active",
            )
        ).first()
        if row is None:
            # Also allow unlinking invite-only roster without follow row
            trainee = self.db.get(models.TraineeProfile, principal.trainee_id)
            if trainee is None or not trainee.trainer_id:
                raise NotFoundError("No active coach relationship.")
            trainer = self.db.get(models.TrainerProfile, trainee.trainer_id)
            profile = (
                self.profiles.get_by_trainer_id(trainee.trainer_id) if trainee.trainer_id else None
            )
            trainee.trainer_id = None
            self.db.add(trainee)
            # Create ended follow record for history if profile exists
            now = _utcnow()
            if profile is not None and trainer is not None:
                row = models.CoachFollow(
                    id=str(uuid4()),
                    coach_profile_id=profile.id,
                    trainer_user_id=trainer.user_id,
                    trainee_user_id=principal.user_id,
                    status="ended",
                    created_at=now,
                    updated_at=now,
                    accepted_at=None,
                    ended_at=now,
                    ended_by_user_id=principal.user_id,
                )
                self.db.add(row)
                self.db.commit()
                self.db.refresh(row)
                if trainer:
                    self._notify(
                        trainer.user_id,
                        notif_type="coach_follow_ended",
                        title="Trainee left",
                        body="A trainee ended their coaching relationship.",
                        data={"type": "coach_follow_ended", "followId": row.id},
                    )
                return self._to_out(row)
            self.db.commit()
            raise NotFoundError("No active coach relationship.")

        return self._end_follow(row, ended_by=principal.user_id, notify_other=True)

    # --- Trainer ------------------------------------------------------------

    def list_for_trainer(
        self, principal: Principal, *, status: str | None = "pending"
    ) -> TrainerFollowPage:
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")
        stmt = (
            select(models.CoachFollow)
            .where(models.CoachFollow.trainer_user_id == principal.user_id)
            .order_by(models.CoachFollow.created_at.desc())
        )
        status_f = (status or "pending").lower()
        if status_f != "all":
            if status_f not in {"pending", "active", "declined", "ended"}:
                raise ValidationAppError(
                    "status must be pending, active, declined, ended, or all.",
                    fields={"status": "invalid"},
                )
            stmt = stmt.where(models.CoachFollow.status == status_f)
        rows = list(self.db.scalars(stmt.limit(100)).all())
        items: list[TrainerFollowItemOut] = []
        for row in rows:
            user = self.db.get(models.User, row.trainee_user_id)
            items.append(
                TrainerFollowItemOut(
                    id=row.id,
                    coach_profile_id=row.coach_profile_id,
                    trainee_user_id=row.trainee_user_id,
                    trainee_name=user.name if user else "Trainee",
                    trainee_avatar_url=user.avatar_url if user else None,
                    status=row.status,
                    package_id=row.package_id,
                    package_title=row.package_title,
                    note=row.note,
                    thread_id=row.thread_id,
                    created_at=row.created_at,
                    accepted_at=row.accepted_at,
                )
            )
        return TrainerFollowPage(items=items)

    def accept(self, principal: Principal, follow_id: str) -> CoachFollowOut:
        row = self._owned_follow(principal, follow_id)
        if row.status != "pending":
            raise ValidationAppError(
                "Only pending requests can be accepted.",
                fields={"status": "invalid"},
            )
        trainee = self.db.scalars(
            select(models.TraineeProfile).where(
                models.TraineeProfile.user_id == row.trainee_user_id
            )
        ).first()
        if trainee is None:
            raise NotFoundError("Trainee no longer exists.")
        profile = self.profiles.get_by_id(row.coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach profile not found.")

        if trainee.trainer_id and trainee.trainer_id != profile.trainer_id:
            raise ConflictError(
                "This trainee is already linked to another coach.",
                fields={"follow": "other_linked"},
            )

        now = _utcnow()
        row.status = "active"
        row.accepted_at = now
        row.updated_at = now
        self.db.add(row)
        self._link_roster(trainee, profile.trainer_id)
        self._analytics_event(profile, row.trainee_user_id, "follow_accepted")
        self.db.commit()
        self.db.refresh(row)

        self._notify(
            row.trainee_user_id,
            notif_type="coach_follow_accepted",
            title="Request accepted",
            body="Your coach accepted your follow request.",
            data={
                "type": "coach_follow_accepted",
                "followId": row.id,
                "coachProfileId": row.coach_profile_id,
            },
        )
        log.info("coach_follow_accepted", follow_id=row.id)
        return self._to_out(row)

    def decline(self, principal: Principal, follow_id: str) -> CoachFollowOut:
        row = self._owned_follow(principal, follow_id)
        if row.status != "pending":
            raise ValidationAppError(
                "Only pending requests can be declined.",
                fields={"status": "invalid"},
            )
        now = _utcnow()
        row.status = "declined"
        row.updated_at = now
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        self._notify(
            row.trainee_user_id,
            notif_type="coach_follow_declined",
            title="Request declined",
            body="Your follow request was declined.",
            data={"type": "coach_follow_declined", "followId": row.id},
        )
        log.info("coach_follow_declined", follow_id=row.id)
        return self._to_out(row)

    def end_as_trainer(self, principal: Principal, follow_id: str) -> CoachFollowOut:
        row = self._owned_follow(principal, follow_id)
        if row.status != "active":
            raise ValidationAppError(
                "Only active relationships can be ended.",
                fields={"status": "invalid"},
            )
        return self._end_follow(row, ended_by=principal.user_id, notify_other=True)

    def follow_status_for_trainee(
        self, principal: Principal, coach_profile_id: str
    ) -> str | None:
        """Cheap status for discovery detail; None if not a trainee."""
        if principal.role != "trainee" or not principal.trainee_id:
            return None
        state = self.get_follow_state(principal, coach_profile_id)
        return state.status

    # --- internals ---------------------------------------------------------

    def _require_trainee(self, principal: Principal) -> None:
        if principal.role != "trainee" or not principal.trainee_id:
            raise ForbiddenError("Trainee access required.")

    def _owned_follow(self, principal: Principal, follow_id: str) -> models.CoachFollow:
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")
        row = self.db.get(models.CoachFollow, follow_id)
        if row is None or row.trainer_user_id != principal.user_id:
            raise NotFoundError("Follow request not found.")
        return row

    def _open_for_pair(
        self, coach_profile_id: str, trainee_user_id: str
    ) -> models.CoachFollow | None:
        return self.db.scalars(
            select(models.CoachFollow).where(
                models.CoachFollow.coach_profile_id == coach_profile_id,
                models.CoachFollow.trainee_user_id == trainee_user_id,
                models.CoachFollow.status.in_(tuple(OPEN_STATUSES)),
            )
        ).first()

    def _open_for_trainee(self, trainee_user_id: str) -> models.CoachFollow | None:
        return self.db.scalars(
            select(models.CoachFollow).where(
                models.CoachFollow.trainee_user_id == trainee_user_id,
                models.CoachFollow.status.in_(tuple(OPEN_STATUSES)),
            )
        ).first()

    def _link_roster(self, trainee: models.TraineeProfile, trainer_id: str) -> None:
        trainee.trainer_id = trainer_id
        self.db.add(trainee)
        self.db.flush()

    def _unlink_roster_if_match(self, trainee_user_id: str, trainer_profile_id: str) -> None:
        trainee = self.db.scalars(
            select(models.TraineeProfile).where(models.TraineeProfile.user_id == trainee_user_id)
        ).first()
        if trainee is not None and trainee.trainer_id == trainer_profile_id:
            trainee.trainer_id = None
            self.db.add(trainee)

    def _end_follow(
        self, row: models.CoachFollow, *, ended_by: str, notify_other: bool
    ) -> CoachFollowOut:
        profile = self.profiles.get_by_id(row.coach_profile_id)
        now = _utcnow()
        row.status = "ended"
        row.ended_at = now
        row.ended_by_user_id = ended_by
        row.updated_at = now
        self.db.add(row)
        if profile is not None:
            self._unlink_roster_if_match(row.trainee_user_id, profile.trainer_id)
        self.db.commit()
        self.db.refresh(row)
        if notify_other:
            other = (
                row.trainee_user_id
                if ended_by == row.trainer_user_id
                else row.trainer_user_id
            )
            self._notify(
                other,
                notif_type="coach_follow_ended",
                title="Relationship ended",
                body="Your coaching relationship has ended.",
                data={"type": "coach_follow_ended", "followId": row.id},
            )
        log.info("coach_follow_ended", follow_id=row.id, ended_by=ended_by)
        return self._to_out(row)

    def _notify(
        self,
        user_id: str,
        *,
        notif_type: str,
        title: str,
        body: str,
        data: dict,
    ) -> None:
        """Inbox + Socket notification.created + APNs (best-effort)."""
        try:
            self.push.notify_sync(
                recipient_user_id=user_id,
                notif_type=notif_type,
                title=title,
                body=body,
                data=data,
                skip_if_online=True,
            )
        except Exception:
            log.exception("follow_notify_failed", user_id=user_id, type=notif_type)

    def _analytics_event(
        self, profile: models.CoachProfile, viewer_user_id: str, event_type: str
    ) -> None:
        try:
            from app.repositories.analytics import AnalyticsRepository

            AnalyticsRepository(self.db).insert_event(
                coach_profile_id=profile.id,
                trainer_id=profile.trainer_id,
                viewer_user_id=viewer_user_id,
                event_type=event_type,
                meta={"source": "follow"},
            )
            self.db.flush()
        except Exception:
            log.exception("follow_analytics_failed", event_type=event_type)

    def _to_out(self, row: models.CoachFollow) -> CoachFollowOut:
        return CoachFollowOut(
            id=row.id,
            coach_profile_id=row.coach_profile_id,
            trainer_user_id=row.trainer_user_id,
            trainee_user_id=row.trainee_user_id,
            status=row.status,
            package_id=row.package_id,
            package_title=row.package_title,
            note=row.note,
            thread_id=row.thread_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            accepted_at=row.accepted_at,
            ended_at=row.ended_at,
        )
