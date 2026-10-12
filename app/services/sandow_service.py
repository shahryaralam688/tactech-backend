"""Live Sandow Score series for Profile (trainee + trainer modes).

Formulas (stable — do not invent random scores):

Trainee ``workout_performance`` (UTC calendar day):
  1. If any form report that day → score = round(avg form.score), clamped 0–100
  2. Else if workout log(s) that day → score = min(100, 70 + 8 * logCount)
  3. Else → 0

Trainer ``boost_analytics`` (when Boost active *now*):
  raw = views + 5*contacts + 0.25*impressions (Phase 6 coach_profile_events)
  score = round(100 * raw / max_raw_in_period) when max_raw > 0, else 0

Trainer ``roster_performance`` (Boost not active):
  Per linked trainee apply trainee daily formula, then score = round(mean across roster).
  Empty roster → all zeros. Also expose activeTrainees / sessionsLogged.

Empty days always emit score 0 (explicit zeros). Timezone: UTC.
``summaryScore`` = round(mean of daily scores with score > 0); if none → 0.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, ValidationAppError
from app.db import models
from app.repositories.analytics import AnalyticsRepository
from app.repositories.coach_profile import CoachProfileRepository
from app.repositories.trainee import TraineeRepository
from app.schemas.sandow import SandowPointOut, SandowScoreOut
from app.services.entitlement_service import EntitlementService

if TYPE_CHECKING:
    from app.api.deps import Principal

WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _period_range(period: str) -> tuple[date, date, str]:
    p = (period or "").strip().lower()
    if p not in ("week", "month"):
        raise ValidationAppError(
            "period must be week or month.",
            fields={"period": "invalid"},
        )
    days = 7 if p == "week" else 30
    to_d = _utcnow().date()
    from_d = to_d - timedelta(days=days - 1)
    return from_d, to_d, p


def _window(from_d: date, to_d: date) -> tuple[datetime, datetime]:
    from_dt = datetime(from_d.year, from_d.month, from_d.day, tzinfo=timezone.utc)
    to_dt = datetime(to_d.year, to_d.month, to_d.day, tzinfo=timezone.utc) + timedelta(days=1)
    return from_dt, to_dt


def _label(d: date) -> str:
    return WEEKDAY_LABELS[d.weekday()]


def _summary(scores: list[int]) -> int:
    active = [s for s in scores if s > 0]
    if not active:
        return 0
    return int(round(sum(active) / len(active)))


def _clamp_score(value: float | int) -> int:
    return max(0, min(100, int(round(value))))


def trainee_day_score(*, form_scores: list[int], log_count: int) -> int:
    """Stable per-day formula — never random."""
    if form_scores:
        return _clamp_score(sum(form_scores) / len(form_scores))
    if log_count > 0:
        return _clamp_score(min(100, 70 + 8 * log_count))
    return 0


def boost_day_raw(*, views: int, contacts: int, impressions: int) -> float:
    return float(views) + 5.0 * float(contacts) + 0.25 * float(impressions)


class SandowService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.trainees = TraineeRepository(db)
        self.profiles = CoachProfileRepository(db)
        self.analytics = AnalyticsRepository(db)
        self.entitlements = EntitlementService(db)

    def get_series(self, principal: Principal, *, period: str = "week") -> SandowScoreOut:
        from_d, to_d, period_key = _period_range(period)
        if principal.role == "trainee":
            if not principal.trainee_id:
                raise ForbiddenError("Trainee access required.")
            return self._trainee_series(principal.trainee_id, from_d, to_d, period_key)
        if principal.role == "trainer":
            if not principal.trainer_id:
                raise ForbiddenError("Trainer access required.")
            boost_active = self.entitlements.is_boost_active(principal.user_id)
            if boost_active:
                return self._boost_series(
                    principal, from_d=from_d, to_d=to_d, period=period_key
                )
            return self._roster_series(
                principal.trainer_id, from_d=from_d, to_d=to_d, period=period_key
            )
        raise ForbiddenError("Unsupported role.")

    # --- Trainee ------------------------------------------------------------

    def _trainee_series(
        self, trainee_id: str, from_d: date, to_d: date, period: str
    ) -> SandowScoreOut:
        form_by, logs_by = self._activity_buckets([trainee_id], from_d, to_d)
        points: list[SandowPointOut] = []
        cur = from_d
        while cur <= to_d:
            forms = form_by.get((trainee_id, cur), [])
            logs = logs_by.get((trainee_id, cur), 0)
            score = trainee_day_score(form_scores=forms, log_count=logs)
            points.append(
                SandowPointOut(date=cur.isoformat(), label=_label(cur), score=score)
            )
            cur += timedelta(days=1)
        summary_label = "This week" if period == "week" else "Last 30 days"
        return SandowScoreOut(
            role="trainee",
            mode="workout_performance",
            period=period,  # type: ignore[arg-type]
            title="Sandow Score",
            subtitle="Workout & form",
            period_from=from_d.isoformat(),
            to=to_d.isoformat(),
            summary_score=_summary([p.score for p in points]),
            summary_label=summary_label,
            points=points,
        )

    # --- Trainer boost ------------------------------------------------------

    def _boost_series(
        self,
        principal: Principal,
        *,
        from_d: date,
        to_d: date,
        period: str,
    ) -> SandowScoreOut:
        profile = self.profiles.get_by_trainer_id(principal.trainer_id)  # type: ignore[arg-type]
        from_dt, to_dt = _window(from_d, to_d)
        if profile is None:
            series_raw: list[dict] = []
            cur = from_d
            while cur <= to_d:
                series_raw.append(
                    {
                        "date": cur.isoformat(),
                        "views": 0,
                        "contacts": 0,
                        "impressions": 0,
                    }
                )
                cur += timedelta(days=1)
        else:
            series_raw = self.analytics.daily_series(
                coach_profile_id=profile.id, from_dt=from_dt, to_dt=to_dt
            )

        raws = [
            boost_day_raw(
                views=int(s["views"]),
                contacts=int(s["contacts"]),
                impressions=int(s["impressions"]),
            )
            for s in series_raw
        ]
        max_raw = max(raws) if raws else 0.0

        points: list[SandowPointOut] = []
        for s, raw in zip(series_raw, raws, strict=True):
            d = date.fromisoformat(s["date"])
            score = _clamp_score(100.0 * raw / max_raw) if max_raw > 0 else 0
            points.append(
                SandowPointOut(
                    date=s["date"],
                    label=_label(d),
                    score=score,
                    views=int(s["views"]),
                    contacts=int(s["contacts"]),
                    impressions=int(s["impressions"]),
                )
            )

        summary_label = "This week" if period == "week" else "Last 30 days"
        return SandowScoreOut(
            role="trainer",
            mode="boost_analytics",
            period=period,  # type: ignore[arg-type]
            title="Boost reach",
            subtitle="Profile views & contacts",
            period_from=from_d.isoformat(),
            to=to_d.isoformat(),
            summary_score=_summary([p.score for p in points]),
            summary_label=summary_label,
            points=points,
            boost_active=True,
        )

    # --- Trainer roster -----------------------------------------------------

    def _roster_series(
        self, trainer_id: str, *, from_d: date, to_d: date, period: str
    ) -> SandowScoreOut:
        roster = self.trainees.list_for_trainer(trainer_id)
        trainee_ids = [t.id for t in roster]
        form_by, logs_by = self._activity_buckets(trainee_ids, from_d, to_d)

        points: list[SandowPointOut] = []
        cur = from_d
        while cur <= to_d:
            day_scores: list[int] = []
            active = 0
            sessions = 0
            for tid in trainee_ids:
                forms = form_by.get((tid, cur), [])
                logs = logs_by.get((tid, cur), 0)
                sc = trainee_day_score(form_scores=forms, log_count=logs)
                day_scores.append(sc)
                if sc > 0:
                    active += 1
                sessions += logs
            if trainee_ids:
                score = _clamp_score(sum(day_scores) / len(day_scores))
            else:
                score = 0
            points.append(
                SandowPointOut(
                    date=cur.isoformat(),
                    label=_label(cur),
                    score=score,
                    active_trainees=active,
                    sessions_logged=sessions,
                )
            )
            cur += timedelta(days=1)

        summary_label = "This week" if period == "week" else "Last 30 days"
        return SandowScoreOut(
            role="trainer",
            mode="roster_performance",
            period=period,  # type: ignore[arg-type]
            title="Clients performance",
            subtitle="Average trainee activity",
            period_from=from_d.isoformat(),
            to=to_d.isoformat(),
            summary_score=_summary([p.score for p in points]),
            summary_label=summary_label,
            points=points,
            boost_active=False,
            trainee_count=len(trainee_ids),
        )

    # --- SQL helpers --------------------------------------------------------

    def _activity_buckets(
        self,
        trainee_ids: list[str],
        from_d: date,
        to_d: date,
    ) -> tuple[dict[tuple[str, date], list[int]], dict[tuple[str, date], int]]:
        """form_by[(trainee_id, day)] = [scores…]; logs_by[(trainee_id, day)] = count."""
        form_by: dict[tuple[str, date], list[int]] = defaultdict(list)
        logs_by: dict[tuple[str, date], int] = defaultdict(int)
        if not trainee_ids:
            return form_by, logs_by

        from_dt, to_dt = _window(from_d, to_d)

        form_day = cast(models.FormReport.created_at, Date).label("day")
        form_stmt = (
            select(
                models.FormReport.trainee_id,
                form_day,
                models.FormReport.score,
            )
            .where(
                models.FormReport.trainee_id.in_(trainee_ids),
                models.FormReport.created_at >= from_dt,
                models.FormReport.created_at < to_dt,
            )
        )
        for row in self.db.execute(form_stmt):
            d = row.day
            if isinstance(d, datetime):
                d = d.date()
            form_by[(row.trainee_id, d)].append(int(row.score))

        log_day = cast(models.WorkoutLog.completed_at, Date).label("day")
        log_stmt = (
            select(
                models.WorkoutLog.trainee_id,
                log_day,
                func.count().label("cnt"),
            )
            .where(
                models.WorkoutLog.trainee_id.in_(trainee_ids),
                models.WorkoutLog.completed_at >= from_dt,
                models.WorkoutLog.completed_at < to_dt,
            )
            .group_by(models.WorkoutLog.trainee_id, log_day)
        )
        for row in self.db.execute(log_stmt):
            d = row.day
            if isinstance(d, datetime):
                d = d.date()
            logs_by[(row.trainee_id, d)] = int(row.cnt)

        return form_by, logs_by
