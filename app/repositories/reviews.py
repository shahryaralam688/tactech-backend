"""Coach reviews repository (Phase 5)."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models

# Auto-hide after this many distinct reporters (documented threshold).
REPORT_HIDE_THRESHOLD = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def encode_review_cursor(*, created_at: datetime, review_id: str) -> str:
    payload = {
        "c": created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "i": review_id,
    }
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def decode_review_cursor(cursor: str) -> tuple[datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    payload = json.loads(raw.decode("utf-8"))
    ts = datetime.fromisoformat(str(payload["c"]).replace("Z", "+00:00"))
    return ts, str(payload["i"])


def display_author_name(full_name: str | None) -> str:
    """Public first name only — never email/phone."""
    if not full_name:
        return "Trainee"
    part = full_name.strip().split()[0] if full_name.strip() else "Trainee"
    return part[:80]


def rating_avg_out(value) -> float | None:
    if value is None:
        return None
    return round(float(value), 1)


class ReviewRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, review_id: str) -> models.CoachReview | None:
        return self.db.get(models.CoachReview, review_id)

    def get_by_author_coach(
        self, *, author_user_id: str, coach_profile_id: str
    ) -> models.CoachReview | None:
        return self.db.scalars(
            select(models.CoachReview).where(
                models.CoachReview.author_user_id == author_user_id,
                models.CoachReview.coach_profile_id == coach_profile_id,
            )
        ).first()

    def create(
        self,
        *,
        coach_profile_id: str,
        trainer_id: str,
        author_user_id: str,
        author_trainee_id: str | None,
        stars: int,
        body: str | None,
    ) -> models.CoachReview:
        now = _utcnow()
        row = models.CoachReview(
            id=str(uuid4()),
            coach_profile_id=coach_profile_id,
            trainer_id=trainer_id,
            author_user_id=author_user_id,
            author_trainee_id=author_trainee_id,
            stars=stars,
            body=body,
            is_hidden=False,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def save(self, row: models.CoachReview) -> models.CoachReview:
        row.updated_at = _utcnow()
        self.db.add(row)
        self.db.flush()
        return row

    def delete(self, row: models.CoachReview) -> None:
        self.db.delete(row)
        self.db.flush()

    def list_for_coach(
        self,
        *,
        coach_profile_id: str,
        viewer_user_id: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[tuple[models.CoachReview, models.User]], str | None]:
        limit = max(1, min(limit, 50))
        stmt = (
            select(models.CoachReview, models.User)
            .join(models.User, models.User.id == models.CoachReview.author_user_id)
            .where(models.CoachReview.coach_profile_id == coach_profile_id)
            .order_by(
                models.CoachReview.created_at.desc(),
                models.CoachReview.id.desc(),
            )
        )
        # Public list excludes hidden; author still sees own hidden review
        if viewer_user_id:
            stmt = stmt.where(
                (models.CoachReview.is_hidden.is_(False))
                | (models.CoachReview.author_user_id == viewer_user_id)
            )
        else:
            stmt = stmt.where(models.CoachReview.is_hidden.is_(False))

        if cursor:
            try:
                cts, cid = decode_review_cursor(cursor)
                stmt = stmt.where(
                    (models.CoachReview.created_at < cts)
                    | (
                        (models.CoachReview.created_at == cts)
                        & (models.CoachReview.id < cid)
                    )
                )
            except Exception:
                pass

        rows = list(self.db.execute(stmt.limit(limit + 1)).all())
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last_review, _ = rows[-1]
            next_cursor = encode_review_cursor(
                created_at=last_review.created_at,
                review_id=last_review.id,
            )
        return rows, next_cursor

    def recompute_aggregates(self, coach_profile_id: str) -> models.CoachProfile | None:
        profile = self.db.get(models.CoachProfile, coach_profile_id)
        if profile is None:
            return None
        avg, count = self.db.execute(
            select(
                func.avg(models.CoachReview.stars),
                func.count(models.CoachReview.id),
            ).where(
                models.CoachReview.coach_profile_id == coach_profile_id,
                models.CoachReview.is_hidden.is_(False),
            )
        ).one()
        if count and int(count) > 0:
            profile.rating_count = int(count)
            profile.rating_avg = Decimal(str(round(float(avg), 2)))
        else:
            profile.rating_count = 0
            profile.rating_avg = None
        self.db.add(profile)
        self.db.flush()
        return profile

    def try_add_report(
        self, *, review_id: str, reporter_user_id: str, reason: str
    ) -> bool:
        """Return True if a new report row was inserted."""
        existing = self.db.scalars(
            select(models.CoachReviewReport).where(
                models.CoachReviewReport.review_id == review_id,
                models.CoachReviewReport.reporter_user_id == reporter_user_id,
            )
        ).first()
        if existing is not None:
            return False
        self.db.add(
            models.CoachReviewReport(
                id=str(uuid4()),
                review_id=review_id,
                reporter_user_id=reporter_user_id,
                reason=reason,
                created_at=_utcnow(),
            )
        )
        try:
            self.db.flush()
        except IntegrityError:
            self.db.expire_all()
            return False
        return True

    def report_count(self, review_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(models.CoachReviewReport)
                .where(models.CoachReviewReport.review_id == review_id)
            )
            or 0
        )
