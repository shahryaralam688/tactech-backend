from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import models
from app.repositories.reviews import rating_avg_out


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def encode_cursor(
    *,
    boost_active: bool,
    rating_avg: float | None,
    is_verified: bool,
    rating_count: int,
    updated_at: datetime,
    profile_id: str,
) -> str:
    payload = {
        "b": 1 if boost_active else 0,
        "rn": 0 if rating_avg is not None else 1,
        "ra": float(rating_avg) if rating_avg is not None else 0.0,
        "v": 1 if is_verified else 0,
        "rc": int(rating_count or 0),
        "u": updated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "i": profile_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[int, int, float, int, int, datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    payload = json.loads(raw.decode("utf-8"))
    ts = datetime.fromisoformat(str(payload["u"]).replace("Z", "+00:00"))
    rn = int(payload.get("rn", 1 if payload.get("ra") is None else 0))
    ra = float(payload.get("ra", 0.0))
    v = int(payload.get("v", 0))
    rc = int(payload.get("rc", 0))
    return int(payload["b"]), rn, ra, v, rc, ts, str(payload["i"])


def _sort_key(
    profile: models.CoachProfile, boost: bool
) -> tuple[int, int, float, int, int, float, str]:
    """boostActive DESC, ratingAvg DESC NULLS LAST, isVerified DESC, ratingCount DESC, updatedAt DESC."""
    avg = float(profile.rating_avg) if profile.rating_avg is not None else None
    return (
        0 if boost else 1,
        0 if avg is not None else 1,
        -(avg if avg is not None else 0.0),
        0 if profile.is_verified else 1,
        -int(profile.rating_count or 0),
        -profile.updated_at.timestamp(),
        profile.id,
    )


class CoachProfileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, profile_id: str) -> models.CoachProfile | None:
        return self.db.get(models.CoachProfile, profile_id)

    def get_by_trainer_id(self, trainer_id: str) -> models.CoachProfile | None:
        return self.db.scalars(
            select(models.CoachProfile).where(models.CoachProfile.trainer_id == trainer_id)
        ).first()

    def get_by_user_id(self, user_id: str) -> models.CoachProfile | None:
        return self.db.scalars(
            select(models.CoachProfile).where(models.CoachProfile.user_id == user_id)
        ).first()

    def create_draft(self, *, trainer_id: str, user_id: str) -> models.CoachProfile:
        now = _utcnow()
        row = models.CoachProfile(
            id=str(uuid4()),
            trainer_id=trainer_id,
            user_id=user_id,
            headline="",
            bio="",
            city="",
            country_code="PK",
            specialties=[],
            languages=[],
            gym_name=None,
            years_experience=None,
            is_public=False,
            cover_image_url=None,
            rating_avg=None,
            rating_count=0,
            is_verified=False,
            verified_at=None,
            verification_status="none",
            follow_mode="manual",
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def save(self, row: models.CoachProfile) -> models.CoachProfile:
        row.updated_at = _utcnow()
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_public(
        self,
        *,
        q: str | None = None,
        city: str | None = None,
        specialty: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
        boost_user_ids: set[str] | None = None,
    ) -> tuple[list[tuple[models.CoachProfile, models.User, bool]], str | None]:
        boost_user_ids = boost_user_ids or set()
        limit = max(1, min(limit, 50))

        stmt = (
            select(models.CoachProfile, models.User)
            .join(models.User, models.User.id == models.CoachProfile.user_id)
            .where(
                models.CoachProfile.is_public.is_(True),
                models.User.deleted_at.is_(None),
            )
        )
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    models.User.name.ilike(pattern),
                    models.CoachProfile.headline.ilike(pattern),
                    models.CoachProfile.city.ilike(pattern),
                )
            )
        if city:
            stmt = stmt.where(models.CoachProfile.city.ilike(city.strip()))
        if specialty:
            stmt = stmt.where(models.CoachProfile.specialties.contains([specialty.strip()]))

        rows = list(self.db.execute(stmt).all())
        enriched: list[tuple[models.CoachProfile, models.User, bool]] = [
            (profile, user, profile.user_id in boost_user_ids) for profile, user in rows
        ]
        enriched.sort(key=lambda item: _sort_key(item[0], item[2]))

        start = 0
        if cursor:
            try:
                cb, crn, cra, cv, crc, cu, cid = decode_cursor(cursor)
                cursor_key = (
                    0 if cb else 1,
                    crn,
                    -cra,
                    0 if cv else 1,
                    -crc,
                    -cu.timestamp(),
                    cid,
                )
            except Exception:
                cursor_key = None  # type: ignore[assignment]
            if cursor_key is not None:
                for idx, (profile, _user, boost) in enumerate(enriched):
                    if _sort_key(profile, boost) > cursor_key:
                        start = idx
                        break
                else:
                    start = len(enriched)

        page = enriched[start : start + limit]
        next_cursor = None
        if len(enriched) > start + limit and page:
            last_profile, _u, last_boost = page[-1]
            next_cursor = encode_cursor(
                boost_active=last_boost,
                rating_avg=rating_avg_out(last_profile.rating_avg),
                is_verified=bool(last_profile.is_verified),
                rating_count=int(last_profile.rating_count or 0),
                updated_at=last_profile.updated_at,
                profile_id=last_profile.id,
            )
        return page, next_cursor
