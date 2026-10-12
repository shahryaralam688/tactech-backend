"""Coach discovery + entitlements DTOs (Phase 1). camelCase via APIModel."""

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel
from app.schemas.packages import FeaturedPackageSummary


class AiEntitlementOut(APIModel):
    active: bool = False
    plan: str | None = None
    plan_display_name: str | None = None
    badge_label: str | None = None
    badge_full_label: str | None = None
    status: str = "inactive"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    renews_at: datetime | None = None
    source: str | None = None
    will_renew: bool | None = False


class BoostEntitlementOut(APIModel):
    active: bool = False
    tier: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    source: str | None = None


class EntitlementsOut(APIModel):
    ai: AiEntitlementOut = Field(default_factory=AiEntitlementOut)
    boost: BoostEntitlementOut = Field(default_factory=BoostEntitlementOut)


class CoachProfileUpdateRequest(APIModel):
    headline: str = Field(default="", max_length=80)
    bio: str = Field(default="", max_length=2000)
    city: str = Field(default="", max_length=120)
    country_code: str = Field(default="PK", min_length=2, max_length=2)
    specialties: list[str] = Field(default_factory=list, max_length=20)
    languages: list[str] = Field(default_factory=list, max_length=20)
    gym_name: str | None = Field(default=None, max_length=255)
    years_experience: int | None = Field(default=None, ge=0)
    is_public: bool = False
    cover_image_url: str | None = Field(default=None, max_length=512)
    # Phase 9 — omit / null = leave unchanged
    follow_mode: str | None = Field(default=None, max_length=32)


class CoachProfilePatchRequest(APIModel):
    """Partial update — only provided fields change (Phase 9 followMode)."""

    headline: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=2000)
    city: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    specialties: list[str] | None = Field(default=None, max_length=20)
    languages: list[str] | None = Field(default=None, max_length=20)
    gym_name: str | None = Field(default=None, max_length=255)
    years_experience: int | None = Field(default=None, ge=0)
    is_public: bool | None = None
    cover_image_url: str | None = Field(default=None, max_length=512)
    follow_mode: str | None = Field(default=None, max_length=32)


class CoachProfileOut(APIModel):
    id: str
    trainer_id: str
    user_id: str
    name: str
    headline: str
    bio: str = ""
    city: str
    country_code: str
    specialties: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    gym_name: str | None = None
    years_experience: int | None = None
    is_public: bool = False
    cover_image_url: str | None = None
    avatar_symbol: str | None = None
    boost_active: bool = False
    rating_avg: float | None = None
    rating_count: int = 0
    is_verified: bool = False
    verified_badge: str | None = None
    packages_count: int = 0
    featured_package: FeaturedPackageSummary | None = None
    follow_mode: str = "manual"  # manual | auto_accept
    updated_at: datetime


class CoachListItemOut(APIModel):
    """List payload — omit full bio for size."""

    id: str
    trainer_id: str
    user_id: str
    name: str
    headline: str
    city: str
    country_code: str
    specialties: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    gym_name: str | None = None
    years_experience: int | None = None
    cover_image_url: str | None = None
    avatar_symbol: str | None = None
    boost_active: bool = False
    rating_avg: float | None = None
    rating_count: int = 0
    is_verified: bool = False
    verified_badge: str | None = None
    packages_count: int = 0
    featured_package: FeaturedPackageSummary | None = None
    updated_at: datetime


class CoachListPage(APIModel):
    items: list[CoachListItemOut]
    next_cursor: str | None = None


class CoachDetailOut(APIModel):
    id: str
    trainer_id: str
    user_id: str
    name: str
    headline: str
    bio: str = ""
    city: str
    country_code: str
    specialties: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    gym_name: str | None = None
    years_experience: int | None = None
    is_public: bool = False
    cover_image_url: str | None = None
    avatar_symbol: str | None = None
    boost_active: bool = False
    rating_avg: float | None = None
    rating_count: int = 0
    is_verified: bool = False
    verified_badge: str | None = None
    packages_count: int = 0
    featured_package: FeaturedPackageSummary | None = None
    follow_mode: str = "manual"
    # Trainee-only; omitted/None for trainers
    follow_status: str | None = None  # none | pending | active | declined | ended
    updated_at: datetime


class CoachContactRequest(APIModel):
    message: str | None = Field(default=None, max_length=1000)


class CoachContactOut(APIModel):
    thread_id: str
    peer_user_id: str
    created: bool


class CoachReviewCreateRequest(APIModel):
    stars: int = Field(ge=1, le=5)
    body: str | None = Field(default=None, max_length=1000)


class CoachReviewOut(APIModel):
    id: str
    coach_profile_id: str
    stars: int
    body: str | None = None
    author_user_id: str
    author_name: str
    created_at: datetime
    updated_at: datetime
    is_mine: bool = False


class CoachReviewListPage(APIModel):
    rating_avg: float | None = None
    rating_count: int = 0
    items: list[CoachReviewOut] = Field(default_factory=list)
    next_cursor: str | None = None


class CoachReviewMineOut(APIModel):
    review: CoachReviewOut | None = None


class CoachReviewReportRequest(APIModel):
    reason: str = Field(min_length=1, max_length=200)


class CoachReviewReportOut(APIModel):
    reported: bool = True
