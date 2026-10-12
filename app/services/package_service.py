"""Coach service packages + inquire (Phase 8).

Price is informational only — no platform checkout/commission in this phase.
Inquire reuses Phase 1 human chat threads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.repositories.chat import ChatRepository
from app.repositories.coach_profile import CoachProfileRepository
from app.schemas.packages import (
    ALLOWED_CURRENCIES,
    ALLOWED_DELIVERY,
    ALLOWED_PERIODS,
    ALLOWED_STATUS,
    CoachPackageOut,
    CoachPackagePage,
    CoachPackageUpsertRequest,
    FeaturedPackageSummary,
    PackageInquireOut,
    PackageInquireRequest,
)

if TYPE_CHECKING:
    from app.api.deps import Principal

log = get_logger("tactech.packages")

MAX_ACTIVE_PACKAGES = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_price_label(*, amount_minor: int, currency: str, billing_period: str) -> str:
    """Consistent inquire/message formatting."""
    cur = (currency or "pkr").lower()
    major = int(amount_minor) / 100.0
    if cur == "pkr":
        # PKR 15,000 (no decimals when whole rupees)
        if abs(major - round(major)) < 1e-9:
            money = f"PKR {int(round(major)):,}"
        else:
            money = f"PKR {major:,.2f}"
    else:
        money = f"${major:,.2f}"
    period = (billing_period or "month").lower()
    suffix = {
        "one_time": "one-time",
        "week": "/ week",
        "month": "/ month",
        "year": "/ year",
        "custom": "",
    }.get(period, f"/ {period}")
    if suffix:
        return f"{money} {suffix}".strip()
    return money


class PackageService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.profiles = CoachProfileRepository(db)
        self.chat = ChatRepository(db)

    # --- Trainer -----------------------------------------------------------

    def list_mine(self, principal: Principal) -> CoachPackagePage:
        profile = self._require_profile(principal)
        rows = list(
            self.db.scalars(
                select(models.CoachPackage)
                .where(models.CoachPackage.coach_profile_id == profile.id)
                .order_by(
                    models.CoachPackage.is_featured.desc(),
                    models.CoachPackage.sort_order.asc(),
                    models.CoachPackage.updated_at.desc(),
                )
            ).all()
        )
        return CoachPackagePage(items=[self._to_out(r) for r in rows])

    def create(self, principal: Principal, payload: CoachPackageUpsertRequest) -> CoachPackageOut:
        profile = self._require_profile(principal)
        fields = self._validate_upsert(payload)
        if fields["status"] == "active":
            self._assert_active_capacity(profile.id, extra=1)
        want_featured = bool(fields["is_featured"]) and fields["status"] == "active"
        fields["is_featured"] = False
        if want_featured:
            self._clear_other_featured(profile.id, except_id="")
        now = _utcnow()
        row = models.CoachPackage(
            id=str(uuid4()),
            coach_profile_id=profile.id,
            trainer_id=profile.trainer_id,
            user_id=principal.user_id,
            created_at=now,
            updated_at=now,
            **fields,
        )
        row.is_featured = want_featured
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        log.info("package_created", package_id=row.id, coach_profile_id=profile.id)
        return self._to_out(row)

    def update(
        self, principal: Principal, package_id: str, payload: CoachPackageUpsertRequest
    ) -> CoachPackageOut:
        profile = self._require_profile(principal)
        row = self._owned_package(profile.id, package_id)
        fields = self._validate_upsert(payload)
        was_active = row.status == "active"
        will_active = fields["status"] == "active"
        if will_active and not was_active:
            self._assert_active_capacity(profile.id, extra=1)
        want_featured = bool(fields["is_featured"]) and will_active
        fields["is_featured"] = False
        if want_featured:
            self._clear_other_featured(profile.id, except_id=row.id)
        for key, value in fields.items():
            setattr(row, key, value)
        row.is_featured = want_featured
        if not will_active:
            row.is_featured = False
        row.updated_at = _utcnow()
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        log.info("package_updated", package_id=row.id)
        return self._to_out(row)

    def archive(self, principal: Principal, package_id: str) -> CoachPackageOut:
        profile = self._require_profile(principal)
        row = self._owned_package(profile.id, package_id)
        row.status = "archived"
        row.is_featured = False
        row.updated_at = _utcnow()
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        log.info("package_archived", package_id=row.id)
        return self._to_out(row)

    # --- Public ------------------------------------------------------------

    def list_public(self, principal: Principal, coach_profile_id: str) -> CoachPackagePage:
        profile = self._visible_profile(principal, coach_profile_id)
        rows = list(
            self.db.scalars(
                select(models.CoachPackage)
                .where(
                    models.CoachPackage.coach_profile_id == profile.id,
                    models.CoachPackage.status == "active",
                )
                .order_by(
                    models.CoachPackage.is_featured.desc(),
                    models.CoachPackage.sort_order.asc(),
                    models.CoachPackage.updated_at.desc(),
                )
            ).all()
        )
        return CoachPackagePage(items=[self._to_out(r, public=True) for r in rows])

    def get_public(
        self, principal: Principal, coach_profile_id: str, package_id: str
    ) -> CoachPackageOut:
        profile = self._visible_profile(principal, coach_profile_id)
        row = self.db.get(models.CoachPackage, package_id)
        if (
            row is None
            or row.coach_profile_id != profile.id
            or row.status != "active"
        ):
            raise NotFoundError("Package not found.")
        return self._to_out(row, public=True)

    def inquire(
        self,
        principal: Principal,
        coach_profile_id: str,
        package_id: str,
        payload: PackageInquireRequest | None,
    ) -> PackageInquireOut:
        if principal.role != "trainee" or not principal.trainee_id:
            raise ForbiddenError("Trainee access required.")
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Package not available.")
        if principal.user_id == profile.user_id:
            raise ForbiddenError("You cannot inquire on your own package.")
        if not self._is_contactable(principal, profile):
            raise NotFoundError("Package not available.")

        row = self.db.get(models.CoachPackage, package_id)
        if (
            row is None
            or row.coach_profile_id != profile.id
            or row.status != "active"
        ):
            raise NotFoundError("Package not available.")

        trainer_user_id = profile.user_id
        existing = self.chat.find_thread(trainer_user_id, principal.user_id)
        created = False
        if existing is None:
            existing = self.chat.create_thread(trainer_user_id, principal.user_id)
            created = True

        price = format_price_label(
            amount_minor=row.amount_minor,
            currency=row.currency,
            billing_period=row.billing_period,
        )
        base = f'I\'m interested in your package "{row.title}" ({price}).'
        extra = ((payload.message if payload else None) or "").strip()
        if extra:
            if len(extra) > 1000:
                raise ValidationAppError(
                    "Message must be at most 1000 characters.",
                    fields={"message": "too_long"},
                )
            text = f"{base}\n\n{extra}"
        else:
            text = base
        if len(text) > 4000:
            text = text[:4000]

        self.chat.add_message(
            existing,
            sender_user_id=principal.user_id,
            sender_role="trainee",
            kind="text",
            text=text,
            bump_unread=True,
        )

        self.db.add(
            models.CoachPackageInquiry(
                id=str(uuid4()),
                package_id=row.id,
                coach_profile_id=profile.id,
                trainee_user_id=principal.user_id,
                thread_id=existing.id,
                created_at=_utcnow(),
            )
        )
        self.db.commit()

        # Reuse Phase 6 contact analytics signal
        from app.services.analytics_service import AnalyticsService
        from app.services.entitlement_service import EntitlementService

        AnalyticsService(self.db).record_contact(
            profile=profile,
            viewer_user_id=principal.user_id,
            created=created,
            boost_active=EntitlementService(self.db).is_boost_active(profile.user_id),
        )

        log.info(
            "package_inquire",
            package_id=row.id,
            thread_id=existing.id,
            trainee_user_id=principal.user_id,
            created=created,
        )
        return PackageInquireOut(
            thread_id=existing.id,
            peer_user_id=trainer_user_id,
            package_id=row.id,
            created=created,
        )

    # --- Discovery helpers -------------------------------------------------

    def summary_for_profiles(
        self, coach_profile_ids: list[str]
    ) -> dict[str, tuple[int, FeaturedPackageSummary | None]]:
        """Return coachProfileId → (packagesCount, featuredPackage|None)."""
        if not coach_profile_ids:
            return {}
        counts = dict(
            self.db.execute(
                select(
                    models.CoachPackage.coach_profile_id,
                    func.count(models.CoachPackage.id),
                )
                .where(
                    models.CoachPackage.coach_profile_id.in_(coach_profile_ids),
                    models.CoachPackage.status == "active",
                )
                .group_by(models.CoachPackage.coach_profile_id)
            ).all()
        )
        featured_rows = list(
            self.db.scalars(
                select(models.CoachPackage).where(
                    models.CoachPackage.coach_profile_id.in_(coach_profile_ids),
                    models.CoachPackage.status == "active",
                    models.CoachPackage.is_featured.is_(True),
                )
            ).all()
        )
        featured_map = {r.coach_profile_id: r for r in featured_rows}
        out: dict[str, tuple[int, FeaturedPackageSummary | None]] = {}
        for pid in coach_profile_ids:
            feat = featured_map.get(pid)
            summary = None
            if feat is not None:
                summary = FeaturedPackageSummary(
                    id=feat.id,
                    title=feat.title,
                    amount_minor=feat.amount_minor,
                    currency=feat.currency,
                    billing_period=feat.billing_period,
                )
            out[pid] = (int(counts.get(pid, 0)), summary)
        return out

    # --- internals ---------------------------------------------------------

    def _require_profile(self, principal: Principal) -> models.CoachProfile:
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")
        profile = self.profiles.get_by_trainer_id(principal.trainer_id)
        if profile is None:
            raise NotFoundError("Coach profile not found. Create your coach profile first.")
        return profile

    def _owned_package(self, coach_profile_id: str, package_id: str) -> models.CoachPackage:
        row = self.db.get(models.CoachPackage, package_id)
        if row is None or row.coach_profile_id != coach_profile_id:
            raise NotFoundError("Package not found.")
        return row

    def _visible_profile(
        self, principal: Principal, coach_profile_id: str
    ) -> models.CoachProfile:
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach not found.")
        if principal.user_id == profile.user_id:
            return profile
        if profile.is_public:
            return profile
        if principal.role == "trainee" and principal.trainee_id:
            trainee = self.db.get(models.TraineeProfile, principal.trainee_id)
            if trainee is not None and trainee.trainer_id == profile.trainer_id:
                return profile
        raise NotFoundError("Coach not found.")

    def _is_contactable(self, principal: Principal, profile: models.CoachProfile) -> bool:
        if profile.is_public:
            return True
        trainee = self.db.get(models.TraineeProfile, principal.trainee_id)
        if trainee is None:
            return False
        return trainee.trainer_id == profile.trainer_id

    def _assert_active_capacity(self, coach_profile_id: str, *, extra: int) -> None:
        count = int(
            self.db.scalar(
                select(func.count())
                .select_from(models.CoachPackage)
                .where(
                    models.CoachPackage.coach_profile_id == coach_profile_id,
                    models.CoachPackage.status == "active",
                )
            )
            or 0
        )
        if count + extra > MAX_ACTIVE_PACKAGES:
            raise ValidationAppError(
                f"You can have at most {MAX_ACTIVE_PACKAGES} active packages.",
                fields={"status": "limit"},
            )

    def _clear_other_featured(self, coach_profile_id: str, *, except_id: str) -> None:
        stmt = (
            update(models.CoachPackage)
            .where(
                models.CoachPackage.coach_profile_id == coach_profile_id,
                models.CoachPackage.is_featured.is_(True),
            )
            .values(is_featured=False, updated_at=_utcnow())
        )
        if except_id:
            stmt = stmt.where(models.CoachPackage.id != except_id)
        self.db.execute(stmt)

    def _validate_upsert(self, payload: CoachPackageUpsertRequest) -> dict:
        title = (payload.title or "").strip()
        if not title:
            raise ValidationAppError("Title is required.", fields={"title": "required"})
        if len(title) > 80:
            raise ValidationAppError("Title must be at most 80 characters.", fields={"title": "too_long"})
        description = (payload.description or "").strip()
        if len(description) > 2000:
            raise ValidationAppError(
                "Description must be at most 2000 characters.",
                fields={"description": "too_long"},
            )
        currency = (payload.currency or "pkr").strip().lower()
        if currency not in ALLOWED_CURRENCIES:
            raise ValidationAppError(
                "currency must be pkr or usd.",
                fields={"currency": "invalid"},
            )
        period = (payload.billing_period or "month").strip().lower()
        if period not in ALLOWED_PERIODS:
            raise ValidationAppError(
                "billingPeriod must be one_time, week, month, year, or custom.",
                fields={"billingPeriod": "invalid"},
            )
        delivery = (payload.delivery or "online").strip().lower()
        if delivery not in ALLOWED_DELIVERY:
            raise ValidationAppError(
                "delivery must be online, in_person, or hybrid.",
                fields={"delivery": "invalid"},
            )
        status = (payload.status or "active").strip().lower()
        if status not in ALLOWED_STATUS:
            raise ValidationAppError(
                "status must be active, archived, or draft.",
                fields={"status": "invalid"},
            )
        includes: list[str] = []
        for raw in payload.includes or []:
            item = (raw or "").strip()
            if not item:
                raise ValidationAppError(
                    "includes must contain non-empty strings.",
                    fields={"includes": "empty_item"},
                )
            if len(item) > 80:
                raise ValidationAppError(
                    "Each include must be at most 80 characters.",
                    fields={"includes": "too_long"},
                )
            includes.append(item)
        if len(includes) > 20:
            raise ValidationAppError(
                "includes may have at most 20 items.",
                fields={"includes": "too_many"},
            )
        if payload.amount_minor < 0:
            raise ValidationAppError(
                "amountMinor must be >= 0.",
                fields={"amountMinor": "invalid"},
            )
        is_featured = bool(payload.is_featured) and status == "active"
        return {
            "title": title,
            "description": description,
            "amount_minor": int(payload.amount_minor),
            "currency": currency,
            "billing_period": period,
            "duration_days": payload.duration_days,
            "includes": includes,
            "delivery": delivery,
            "status": status,
            "is_featured": is_featured,
            "sort_order": int(payload.sort_order or 0),
        }

    def _to_out(self, row: models.CoachPackage, *, public: bool = False) -> CoachPackageOut:
        return CoachPackageOut(
            id=row.id,
            coach_profile_id=row.coach_profile_id,
            title=row.title,
            description=row.description or "",
            amount_minor=row.amount_minor,
            currency=row.currency,
            billing_period=row.billing_period,
            duration_days=row.duration_days,
            includes=list(row.includes or []),
            delivery=row.delivery,
            status=row.status,
            is_featured=bool(row.is_featured),
            sort_order=int(row.sort_order or 0),
            created_at=None if public else row.created_at,
            updated_at=row.updated_at,
        )
