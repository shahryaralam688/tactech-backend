"""Coach discovery analytics events (Phase 6)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.db import models

EVENT_VIEW = "view"
EVENT_IMPRESSION = "impression"
EVENT_CONTACT = "contact"
EVENT_CONTACT_CREATED = "contact_created"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnalyticsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def insert_event(
        self,
        *,
        coach_profile_id: str,
        trainer_id: str,
        viewer_user_id: str | None,
        event_type: str,
        meta: dict | None = None,
        created_at: datetime | None = None,
    ) -> models.CoachProfileEvent:
        row = models.CoachProfileEvent(
            id=str(uuid4()),
            coach_profile_id=coach_profile_id,
            trainer_id=trainer_id,
            viewer_user_id=viewer_user_id,
            event_type=event_type,
            created_at=created_at or _utcnow(),
            meta=meta,
        )
        self.db.add(row)
        return row

    def commit(self) -> None:
        self.db.commit()

    def flush(self) -> None:
        self.db.flush()

    def totals(
        self,
        *,
        coach_profile_id: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> dict[str, int]:
        """SQL aggregates — never returns viewer identities."""
        base = (
            select(
                models.CoachProfileEvent.event_type,
                func.count().label("cnt"),
            )
            .where(
                models.CoachProfileEvent.coach_profile_id == coach_profile_id,
                models.CoachProfileEvent.created_at >= from_dt,
                models.CoachProfileEvent.created_at < to_dt,
            )
            .group_by(models.CoachProfileEvent.event_type)
        )
        by_type = {row.event_type: int(row.cnt) for row in self.db.execute(base)}

        unique_viewers = self.db.scalar(
            select(func.count(func.distinct(models.CoachProfileEvent.viewer_user_id))).where(
                models.CoachProfileEvent.coach_profile_id == coach_profile_id,
                models.CoachProfileEvent.event_type == EVENT_VIEW,
                models.CoachProfileEvent.created_at >= from_dt,
                models.CoachProfileEvent.created_at < to_dt,
                models.CoachProfileEvent.viewer_user_id.is_not(None),
            )
        )
        return {
            "views": by_type.get(EVENT_VIEW, 0),
            "uniqueViewers": int(unique_viewers or 0),
            "impressions": by_type.get(EVENT_IMPRESSION, 0),
            "contacts": by_type.get(EVENT_CONTACT, 0),
            "contactsCreated": by_type.get(EVENT_CONTACT_CREATED, 0),
        }

    def daily_series(
        self,
        *,
        coach_profile_id: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[dict]:
        """One UTC calendar day bucket per date in [from, to)."""
        day_col = cast(models.CoachProfileEvent.created_at, Date).label("day")
        stmt = (
            select(
                day_col,
                models.CoachProfileEvent.event_type,
                func.count().label("cnt"),
                func.count(func.distinct(models.CoachProfileEvent.viewer_user_id)).label(
                    "uniq"
                ),
            )
            .where(
                models.CoachProfileEvent.coach_profile_id == coach_profile_id,
                models.CoachProfileEvent.created_at >= from_dt,
                models.CoachProfileEvent.created_at < to_dt,
            )
            .group_by(day_col, models.CoachProfileEvent.event_type)
        )
        # day -> metrics
        buckets: dict[date, dict[str, int]] = {}
        for row in self.db.execute(stmt):
            d = row.day
            if isinstance(d, datetime):
                d = d.date()
            slot = buckets.setdefault(
                d, {"views": 0, "uniqueViewers": 0, "impressions": 0, "contacts": 0}
            )
            if row.event_type == EVENT_VIEW:
                slot["views"] = int(row.cnt)
                slot["uniqueViewers"] = int(row.uniq or 0)
            elif row.event_type == EVENT_IMPRESSION:
                slot["impressions"] = int(row.cnt)
            elif row.event_type == EVENT_CONTACT:
                slot["contacts"] = int(row.cnt)

        start = from_dt.astimezone(timezone.utc).date()
        end = (to_dt.astimezone(timezone.utc) - timedelta(microseconds=1)).date()
        series: list[dict] = []
        cur = start
        while cur <= end:
            slot = buckets.get(
                cur, {"views": 0, "uniqueViewers": 0, "impressions": 0, "contacts": 0}
            )
            series.append(
                {
                    "date": cur.isoformat(),
                    "views": slot["views"],
                    "uniqueViewers": slot["uniqueViewers"],
                    "impressions": slot["impressions"],
                    "contacts": slot["contacts"],
                }
            )
            cur += timedelta(days=1)
        return series

    def boost_active_days(
        self,
        *,
        user_id: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> int:
        """Distinct UTC dates in [from, to) intersecting any boost window."""
        rows = list(
            self.db.scalars(
                select(models.CoachBoost).where(
                    models.CoachBoost.user_id == user_id,
                    models.CoachBoost.starts_at.is_not(None),
                    models.CoachBoost.ends_at.is_not(None),
                    models.CoachBoost.starts_at < to_dt,
                    models.CoachBoost.ends_at > from_dt,
                    models.CoachBoost.status.in_(["active", "expired", "canceled"]),
                )
            ).all()
        )
        days: set[date] = set()
        period_start = from_dt.astimezone(timezone.utc).date()
        period_end = (to_dt.astimezone(timezone.utc) - timedelta(microseconds=1)).date()
        for boost in rows:
            if boost.starts_at is None or boost.ends_at is None:
                continue
            # Window is [starts_at, ends_at)
            b_start = max(boost.starts_at.astimezone(timezone.utc).date(), period_start)
            # last active calendar day is the day before ends_at if ends_at is midnight-aligned,
            # else the date of ends_at - 1µs
            ends = boost.ends_at.astimezone(timezone.utc)
            last = (ends - timedelta(microseconds=1)).date()
            b_end = min(last, period_end)
            cur = b_start
            while cur <= b_end:
                days.add(cur)
                cur += timedelta(days=1)
        return len(days)

    def recent_impression_exists(
        self,
        *,
        coach_profile_id: str,
        viewer_user_id: str,
        within_seconds: int = 900,
    ) -> bool:
        since = _utcnow() - timedelta(seconds=within_seconds)
        row = self.db.scalars(
            select(models.CoachProfileEvent.id)
            .where(
                models.CoachProfileEvent.coach_profile_id == coach_profile_id,
                models.CoachProfileEvent.viewer_user_id == viewer_user_id,
                models.CoachProfileEvent.event_type == EVENT_IMPRESSION,
                models.CoachProfileEvent.created_at >= since,
            )
            .limit(1)
        ).first()
        return row is not None
