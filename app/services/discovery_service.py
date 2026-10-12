"""Coach discovery + free contact (Phase 1). No payments / entitlements gating."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.repositories.chat import ChatRepository
from app.repositories.coach_profile import CoachProfileRepository
from app.repositories.reviews import rating_avg_out
from app.schemas.discovery import (
    CoachContactOut,
    CoachDetailOut,
    CoachListItemOut,
    CoachListPage,
    CoachProfileOut,
    CoachProfilePatchRequest,
    CoachProfileUpdateRequest,
)
from app.services.entitlement_service import EntitlementService

if TYPE_CHECKING:
    from app.api.deps import Principal

log = get_logger("tactech.discovery")


def _verified_badge(is_verified: bool) -> str | None:
    return "Verified Coach" if is_verified else None


def _clean_str_list(values: list[str] | None, *, field: str, max_items: int = 20) -> list[str]:
    if values is None:
        return []
    cleaned: list[str] = []
    for raw in values:
        item = (raw or "").strip()
        if not item:
            raise ValidationAppError(
                f"{field} must contain non-empty strings.",
                fields={field: "empty_item"},
            )
        cleaned.append(item)
    if len(cleaned) > max_items:
        raise ValidationAppError(
            f"{field} may have at most {max_items} items.",
            fields={field: "too_many"},
        )
    return cleaned


class DiscoveryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.profiles = CoachProfileRepository(db)
        self.entitlements = EntitlementService(db)
        self.chat = ChatRepository(db)

    # --- /me/coach-profile -------------------------------------------------

    def get_or_create_my_profile(self, principal: Principal) -> CoachProfileOut:
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")
        row = self.profiles.get_by_trainer_id(principal.trainer_id)
        if row is None:
            row = self.profiles.create_draft(
                trainer_id=principal.trainer_id,
                user_id=principal.user_id,
            )
            log.info(
                "coach_profile_draft_created",
                profile_id=row.id,
                trainer_id=principal.trainer_id,
                user_id=principal.user_id,
            )
        return self._owner_out(row)

    def update_my_profile(
        self, principal: Principal, payload: CoachProfileUpdateRequest
    ) -> CoachProfileOut:
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")
        row = self.profiles.get_by_trainer_id(principal.trainer_id)
        if row is None:
            row = self.profiles.create_draft(
                trainer_id=principal.trainer_id,
                user_id=principal.user_id,
            )

        headline = (payload.headline or "").strip()
        bio = (payload.bio or "").strip()
        city = (payload.city or "").strip()
        country = (payload.country_code or "PK").strip().upper()
        gym = (payload.gym_name or "").strip() or None
        from app.core.storage import normalize_client_media_url
        from app.core.config import get_settings

        cover = normalize_client_media_url(
            get_settings(), (payload.cover_image_url or "").strip() or None
        )
        specialties = _clean_str_list(payload.specialties, field="specialties")
        languages = _clean_str_list(payload.languages, field="languages")

        if len(headline) > 80:
            raise ValidationAppError("Headline must be at most 80 characters.", fields={"headline": "too_long"})
        if len(bio) > 2000:
            raise ValidationAppError("Bio must be at most 2000 characters.", fields={"bio": "too_long"})
        if len(country) != 2:
            raise ValidationAppError("countryCode must be 2 letters.", fields={"countryCode": "invalid"})
        if payload.years_experience is not None and payload.years_experience < 0:
            raise ValidationAppError(
                "yearsExperience must be null or >= 0.",
                fields={"yearsExperience": "invalid"},
            )

        if payload.is_public:
            if not headline:
                raise ValidationAppError(
                    "Headline is required to make your coach profile public.",
                    fields={"headline": "required"},
                )
            if not city:
                raise ValidationAppError(
                    "City is required to make your coach profile public.",
                    fields={"city": "required"},
                )
            if len(specialties) < 1:
                raise ValidationAppError(
                    "Add at least one specialty to make your coach profile public.",
                    fields={"specialties": "required"},
                )

        row.headline = headline
        row.bio = bio
        row.city = city
        row.country_code = country
        row.specialties = specialties
        row.languages = languages
        row.gym_name = gym
        row.years_experience = payload.years_experience
        row.is_public = bool(payload.is_public)
        row.cover_image_url = cover
        if payload.follow_mode is not None:
            mode = (payload.follow_mode or "").strip().lower()
            if mode not in {"manual", "auto_accept"}:
                raise ValidationAppError(
                    "followMode must be manual or auto_accept.",
                    fields={"followMode": "invalid"},
                )
            row.follow_mode = mode
        saved = self.profiles.save(row)
        log.info(
            "coach_profile_updated",
            profile_id=saved.id,
            trainer_id=principal.trainer_id,
            is_public=saved.is_public,
        )
        return self._owner_out(saved)

    def patch_my_profile(
        self, principal: Principal, payload: CoachProfilePatchRequest
    ) -> CoachProfileOut:
        """Partial update — only non-null fields apply (safe for followMode-only)."""
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")
        row = self.profiles.get_by_trainer_id(principal.trainer_id)
        if row is None:
            row = self.profiles.create_draft(
                trainer_id=principal.trainer_id,
                user_id=principal.user_id,
            )

        if payload.headline is not None:
            headline = payload.headline.strip()
            if len(headline) > 80:
                raise ValidationAppError(
                    "Headline must be at most 80 characters.",
                    fields={"headline": "too_long"},
                )
            row.headline = headline
        if payload.bio is not None:
            bio = payload.bio.strip()
            if len(bio) > 2000:
                raise ValidationAppError(
                    "Bio must be at most 2000 characters.", fields={"bio": "too_long"}
                )
            row.bio = bio
        if payload.city is not None:
            row.city = payload.city.strip()
        if payload.country_code is not None:
            country = payload.country_code.strip().upper()
            if len(country) != 2:
                raise ValidationAppError(
                    "countryCode must be 2 letters.", fields={"countryCode": "invalid"}
                )
            row.country_code = country
        if payload.specialties is not None:
            row.specialties = _clean_str_list(payload.specialties, field="specialties")
        if payload.languages is not None:
            row.languages = _clean_str_list(payload.languages, field="languages")
        if payload.gym_name is not None:
            row.gym_name = payload.gym_name.strip() or None
        if payload.years_experience is not None:
            if payload.years_experience < 0:
                raise ValidationAppError(
                    "yearsExperience must be null or >= 0.",
                    fields={"yearsExperience": "invalid"},
                )
            row.years_experience = payload.years_experience
        if payload.cover_image_url is not None:
            from app.core.storage import normalize_client_media_url
            from app.core.config import get_settings

            row.cover_image_url = normalize_client_media_url(
                get_settings(), payload.cover_image_url.strip() or None
            )
        if payload.is_public is not None:
            row.is_public = bool(payload.is_public)
        if payload.follow_mode is not None:
            mode = payload.follow_mode.strip().lower()
            if mode not in {"manual", "auto_accept"}:
                raise ValidationAppError(
                    "followMode must be manual or auto_accept.",
                    fields={"followMode": "invalid"},
                )
            row.follow_mode = mode

        if row.is_public:
            if not (row.headline or "").strip():
                raise ValidationAppError(
                    "Headline is required to make your coach profile public.",
                    fields={"headline": "required"},
                )
            if not (row.city or "").strip():
                raise ValidationAppError(
                    "City is required to make your coach profile public.",
                    fields={"city": "required"},
                )
            if len(list(row.specialties or [])) < 1:
                raise ValidationAppError(
                    "Add at least one specialty to make your coach profile public.",
                    fields={"specialties": "required"},
                )

        saved = self.profiles.save(row)
        log.info(
            "coach_profile_patched",
            profile_id=saved.id,
            trainer_id=principal.trainer_id,
            is_public=saved.is_public,
            follow_mode=saved.follow_mode,
        )
        return self._owner_out(saved)

    # --- Discovery ---------------------------------------------------------

    def list_coaches(
        self,
        *,
        q: str | None = None,
        city: str | None = None,
        specialty: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CoachListPage:
        from app.repositories.billing import BillingRepository

        BillingRepository(self.db).expire_stale()
        # Preload boost set for ranking (live windows from coach_boosts).
        user_ids = list(
            self.db.scalars(
                select(models.CoachProfile.user_id).where(models.CoachProfile.is_public.is_(True))
            ).all()
        )
        boost_ids = self.entitlements.active_boost_user_ids(user_ids)

        page, next_cursor = self.profiles.list_public(
            q=q,
            city=city,
            specialty=specialty,
            cursor=cursor,
            limit=limit,
            boost_user_ids=boost_ids,
        )
        from app.services.package_service import PackageService

        pkg_summary = PackageService(self.db).summary_for_profiles([p.id for p, _u, _b in page])
        items = []
        for profile, user, boost in page:
            count, featured = pkg_summary.get(profile.id, (0, None))
            items.append(
                CoachListItemOut(
                    id=profile.id,
                    trainer_id=profile.trainer_id,
                    user_id=profile.user_id,
                    name=user.name,
                    headline=profile.headline,
                    city=profile.city,
                    country_code=profile.country_code,
                    specialties=list(profile.specialties or []),
                    languages=list(profile.languages or []),
                    gym_name=profile.gym_name,
                    years_experience=profile.years_experience,
                    cover_image_url=profile.cover_image_url,
                    avatar_symbol=user.avatar_asset,
                    boost_active=boost,
                    rating_avg=rating_avg_out(profile.rating_avg),
                    rating_count=int(profile.rating_count or 0),
                    is_verified=bool(profile.is_verified),
                    verified_badge=_verified_badge(bool(profile.is_verified)),
                    packages_count=count,
                    featured_package=featured,
                    updated_at=profile.updated_at,
                )
            )
        return CoachListPage(items=items, next_cursor=next_cursor)

    def get_coach(self, principal: Principal, coach_profile_id: str) -> CoachDetailOut:
        row = self.profiles.get_by_id(coach_profile_id)
        if row is None:
            raise NotFoundError("Coach not found.")
        is_owner = principal.user_id == row.user_id
        if not row.is_public and not is_owner:
            raise NotFoundError("Coach not found.")
        user = self.db.get(models.User, row.user_id)
        if user is None or user.deleted_at is not None:
            raise NotFoundError("Coach not found.")
        boost = self.entitlements.is_boost_active(row.user_id)
        from app.services.package_service import PackageService

        count, featured = PackageService(self.db).summary_for_profiles([row.id]).get(
            row.id, (0, None)
        )
        follow_status = None
        if principal.role == "trainee" and principal.trainee_id:
            from app.services.follow_service import FollowService

            follow_status = FollowService(self.db).follow_status_for_trainee(
                principal, row.id
            )

        out = CoachDetailOut(
            id=row.id,
            trainer_id=row.trainer_id,
            user_id=row.user_id,
            name=user.name,
            headline=row.headline,
            bio=row.bio or "",
            city=row.city,
            country_code=row.country_code,
            specialties=list(row.specialties or []),
            languages=list(row.languages or []),
            gym_name=row.gym_name,
            years_experience=row.years_experience,
            is_public=row.is_public,
            cover_image_url=row.cover_image_url,
            avatar_symbol=user.avatar_asset,
            boost_active=boost,
            rating_avg=rating_avg_out(row.rating_avg),
            rating_count=int(row.rating_count or 0),
            is_verified=bool(row.is_verified),
            verified_badge=_verified_badge(bool(row.is_verified)),
            packages_count=count,
            featured_package=featured,
            follow_mode=row.follow_mode or "manual",
            follow_status=follow_status,
            updated_at=row.updated_at,
        )
        # Phase 6 — privacy-safe view event (non-owner only); after DTO so commit can't expire attrs
        if principal.user_id != row.user_id:
            from app.services.analytics_service import AnalyticsService

            AnalyticsService(self.db).record_view(
                profile=row,
                viewer_user_id=principal.user_id,
                boost_active=boost,
            )
        return out

    def contact_coach(
        self,
        principal: Principal,
        coach_profile_id: str,
        *,
        message: str | None = None,
    ) -> CoachContactOut:
        if principal.role != "trainee" or not principal.trainee_id:
            raise ForbiddenError("Trainee access required.")

        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach not available.")

        if principal.user_id == profile.user_id:
            raise ForbiddenError("You cannot contact yourself.")

        if not self._is_contactable(principal, profile):
            raise NotFoundError("Coach not available.")

        trainer_user_id = profile.user_id
        trainee_user_id = principal.user_id
        existing = self.chat.find_thread(trainer_user_id, trainee_user_id)
        created = False
        if existing is None:
            existing = self.chat.create_thread(trainer_user_id, trainee_user_id)
            created = True

        # Prefer append whenever message is provided (new or existing thread).
        cleaned = (message or "").strip()
        if cleaned:
            if len(cleaned) > 1000:
                raise ValidationAppError(
                    "Message must be at most 1000 characters.",
                    fields={"message": "too_long"},
                )
            self.chat.add_message(
                existing,
                sender_user_id=principal.user_id,
                sender_role="trainee",
                kind="text",
                text=cleaned,
                bump_unread=True,
            )

        log.info(
            "coach_contact",
            coach_profile_id=coach_profile_id,
            thread_id=existing.id,
            trainee_user_id=trainee_user_id,
            peer_user_id=trainer_user_id,
            created=created,
            has_message=bool(cleaned),
        )
        # Phase 6 — contact analytics (includes reused threads)
        from app.services.analytics_service import AnalyticsService

        AnalyticsService(self.db).record_contact(
            profile=profile,
            viewer_user_id=trainee_user_id,
            created=created,
            boost_active=self.entitlements.is_boost_active(profile.user_id),
        )
        return CoachContactOut(
            thread_id=existing.id,
            peer_user_id=trainer_user_id,
            created=created,
        )

    def _is_contactable(self, principal: Principal, profile: models.CoachProfile) -> bool:
        if profile.is_public:
            return True
        # Linked via existing invite/link relationship
        trainee = self.db.get(models.TraineeProfile, principal.trainee_id)
        if trainee is None:
            return False
        return trainee.trainer_id == profile.trainer_id

    def _owner_out(self, row: models.CoachProfile) -> CoachProfileOut:
        user = self.db.get(models.User, row.user_id)
        name = user.name if user else ""
        avatar = user.avatar_asset if user else None
        boost = self.entitlements.is_boost_active(row.user_id)
        from app.services.package_service import PackageService

        count, featured = PackageService(self.db).summary_for_profiles([row.id]).get(
            row.id, (0, None)
        )
        return CoachProfileOut(
            id=row.id,
            trainer_id=row.trainer_id,
            user_id=row.user_id,
            name=name,
            headline=row.headline,
            bio=row.bio or "",
            city=row.city,
            country_code=row.country_code,
            specialties=list(row.specialties or []),
            languages=list(row.languages or []),
            gym_name=row.gym_name,
            years_experience=row.years_experience,
            is_public=row.is_public,
            cover_image_url=row.cover_image_url,
            avatar_symbol=avatar,
            boost_active=boost,
            rating_avg=rating_avg_out(row.rating_avg),
            rating_count=int(row.rating_count or 0),
            is_verified=bool(row.is_verified),
            verified_badge=_verified_badge(bool(row.is_verified)),
            packages_count=count,
            featured_package=featured,
            follow_mode=row.follow_mode or "manual",
            updated_at=row.updated_at,
        )
