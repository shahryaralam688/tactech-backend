"""Trainer discovery analytics (Phase 6). Aggregates only — no viewer PII."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.repositories.analytics import (
    EVENT_CONTACT,
    EVENT_CONTACT_CREATED,
    EVENT_IMPRESSION,
    EVENT_VIEW,
    AnalyticsRepository,
)
from app.repositories.coach_profile import CoachProfileRepository
from app.repositories.reviews import rating_avg_out
from app.schemas.analytics import (
    AnalyticsBoostOut,
    AnalyticsDayOut,
    AnalyticsTotalsOut,
    CoachAnalyticsOut,
    CoachAnalyticsSummaryOut,
    ImpressionsOut,
    ImpressionsRequest,
)
from app.services.entitlement_service import EntitlementService

if TYPE_CHECKING:
    from app.api.deps import Principal

log = get_logger("tactech.analytics")

ALLOWED_PERIODS = frozenset({7, 30, 90})
IMPRESSION_DEDUPE_SECONDS = 15 * 60


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _period_bounds(period_days: int) -> tuple[datetime, datetime, int]:
    if period_days not in ALLOWED_PERIODS:
        raise ValidationAppError(
            "periodDays must be 7, 30, or 90.",
            fields={"periodDays": "invalid"},
        )
    to_dt = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    from_dt = to_dt - timedelta(days=period_days)
    return from_dt, to_dt, period_days


class AnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = AnalyticsRepository(db)
        self.profiles = CoachProfileRepository(db)
        self.entitlements = EntitlementService(db)

    # --- Instrumentation ---------------------------------------------------

    def record_view(
        self,
        *,
        profile: models.CoachProfile,
        viewer_user_id: str,
        boost_active: bool,
    ) -> None:
        if viewer_user_id == profile.user_id:
            return
        try:
            self.repo.insert_event(
                coach_profile_id=profile.id,
                trainer_id=profile.trainer_id,
                viewer_user_id=viewer_user_id,
                event_type=EVENT_VIEW,
                meta={"source": "detail", "boostActive": bool(boost_active)},
            )
            self.repo.flush()
            self.db.commit()
        except Exception:
            self.db.rollback()
            log.exception("analytics_view_failed", coach_profile_id=profile.id)

    def record_contact(
        self,
        *,
        profile: models.CoachProfile,
        viewer_user_id: str,
        created: bool,
        boost_active: bool,
    ) -> None:
        if viewer_user_id == profile.user_id:
            return
        try:
            self.repo.insert_event(
                coach_profile_id=profile.id,
                trainer_id=profile.trainer_id,
                viewer_user_id=viewer_user_id,
                event_type=EVENT_CONTACT,
                meta={"source": "contact", "boostActive": bool(boost_active), "created": created},
            )
            if created:
                self.repo.insert_event(
                    coach_profile_id=profile.id,
                    trainer_id=profile.trainer_id,
                    viewer_user_id=viewer_user_id,
                    event_type=EVENT_CONTACT_CREATED,
                    meta={"source": "contact", "boostActive": bool(boost_active)},
                )
            self.repo.flush()
            self.db.commit()
        except Exception:
            self.db.rollback()
            log.exception("analytics_contact_failed", coach_profile_id=profile.id)

    def record_impressions(
        self, principal: Principal, payload: ImpressionsRequest
    ) -> ImpressionsOut:
        ids = list(dict.fromkeys((payload.coach_profile_ids or [])[:50]))
        if not ids:
            return ImpressionsOut(recorded=0)
        source = (payload.source or "discover_list").strip()[:64] or "discover_list"
        recorded = 0
        for pid in ids:
            profile = self.profiles.get_by_id(pid)
            if profile is None or not profile.is_public:
                continue
            if profile.user_id == principal.user_id:
                continue
            if self.repo.recent_impression_exists(
                coach_profile_id=profile.id,
                viewer_user_id=principal.user_id,
                within_seconds=IMPRESSION_DEDUPE_SECONDS,
            ):
                continue
            boost = self.entitlements.is_boost_active(profile.user_id)
            self.repo.insert_event(
                coach_profile_id=profile.id,
                trainer_id=profile.trainer_id,
                viewer_user_id=principal.user_id,
                event_type=EVENT_IMPRESSION,
                meta={"source": source, "boostActive": boost},
            )
            recorded += 1
        if recorded:
            self.db.commit()
        return ImpressionsOut(recorded=recorded)

    # --- Trainer reads -----------------------------------------------------

    def get_analytics(
        self, principal: Principal, *, period_days: int = 30, include_series: bool = True
    ) -> CoachAnalyticsOut | CoachAnalyticsSummaryOut:
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")
        profile = self.profiles.get_by_trainer_id(principal.trainer_id)
        if profile is None:
            raise NotFoundError("Coach profile not found.")

        from_dt, to_dt, days = _period_bounds(period_days)
        raw = self.repo.totals(
            coach_profile_id=profile.id, from_dt=from_dt, to_dt=to_dt
        )
        boost_days = self.repo.boost_active_days(
            user_id=profile.user_id, from_dt=from_dt, to_dt=to_dt
        )
        boost_row = self.entitlements.repo.active_boost_for_user(profile.user_id)
        totals = AnalyticsTotalsOut(
            views=raw["views"],
            unique_viewers=raw["uniqueViewers"],
            impressions=raw["impressions"],
            contacts=raw["contacts"],
            contacts_created=raw["contactsCreated"],
            rating_avg=rating_avg_out(profile.rating_avg),
            rating_count=int(profile.rating_count or 0),
            boost_active_days=boost_days,
        )
        boost = AnalyticsBoostOut(
            active_now=boost_row is not None,
            ends_at=boost_row.ends_at if boost_row else None,
        )
        if not include_series:
            return CoachAnalyticsSummaryOut(
                coach_profile_id=profile.id,
                period_days=days,
                period_from=from_dt,
                to=to_dt,
                totals=totals,
                boost=boost,
            )
        series_raw = self.repo.daily_series(
            coach_profile_id=profile.id, from_dt=from_dt, to_dt=to_dt
        )
        series = [
            AnalyticsDayOut(
                date=s["date"],
                views=s["views"],
                unique_viewers=s["uniqueViewers"],
                impressions=s["impressions"],
                contacts=s["contacts"],
            )
            for s in series_raw
        ]
        return CoachAnalyticsOut(
            coach_profile_id=profile.id,
            period_days=days,
            period_from=from_dt,
            to=to_dt,
            totals=totals,
            series=series,
            boost=boost,
        )
