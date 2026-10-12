from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class EntitlementsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def active_ai_for_user(self, user_id: str, *, now: datetime | None = None) -> models.AiEntitlement | None:
        """Active if status in (active, grace, billing_retry) and endsAt > now (or null)."""
        now = now or _utcnow()
        row = self.db.scalars(
            select(models.AiEntitlement).where(models.AiEntitlement.user_id == user_id)
        ).first()
        if row is None:
            return None
        if row.status not in {"active", "grace", "billing_retry"}:
            return None
        if row.ends_at is not None:
            ends = _aware(row.ends_at)
            if ends is None or ends <= now:
                return None
        return row

    def active_boost_for_user(self, user_id: str, *, now: datetime | None = None) -> models.CoachBoost | None:
        now = now or _utcnow()
        return self.db.scalars(
            select(models.CoachBoost)
            .where(
                models.CoachBoost.user_id == user_id,
                models.CoachBoost.status == "active",
                models.CoachBoost.starts_at.is_not(None),
                models.CoachBoost.ends_at.is_not(None),
                models.CoachBoost.starts_at <= now,
                models.CoachBoost.ends_at > now,
            )
            .order_by(models.CoachBoost.ends_at.desc())
        ).first()

    def active_boost_user_ids(self, user_ids: list[str], *, now: datetime | None = None) -> set[str]:
        if not user_ids:
            return set()
        now = now or _utcnow()
        rows = self.db.scalars(
            select(models.CoachBoost.user_id).where(
                models.CoachBoost.user_id.in_(user_ids),
                models.CoachBoost.status == "active",
                models.CoachBoost.starts_at.is_not(None),
                models.CoachBoost.ends_at.is_not(None),
                models.CoachBoost.starts_at <= now,
                models.CoachBoost.ends_at > now,
            )
        ).all()
        return set(rows)

    def is_window_active(
        self,
        *,
        starts_at: datetime | None,
        ends_at: datetime | None,
        status: str | None,
        now: datetime | None = None,
    ) -> bool:
        now = now or _utcnow()
        starts = _aware(starts_at)
        ends = _aware(ends_at)
        if starts is None or ends is None:
            return False
        if status and status != "active":
            return False
        return starts <= now < ends
