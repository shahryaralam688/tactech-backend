"""Coach packages DTOs (Phase 8). Price is display-only — no platform charge."""

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel

ALLOWED_CURRENCIES = frozenset({"pkr", "usd"})
ALLOWED_PERIODS = frozenset({"one_time", "week", "month", "year", "custom"})
ALLOWED_DELIVERY = frozenset({"online", "in_person", "hybrid"})
ALLOWED_STATUS = frozenset({"active", "archived", "draft"})


class CoachPackageUpsertRequest(APIModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    amount_minor: int = Field(ge=0)
    currency: str = Field(default="pkr", max_length=8)
    billing_period: str = Field(default="month", max_length=32)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    includes: list[str] = Field(default_factory=list, max_length=20)
    delivery: str = Field(default="online", max_length=32)
    status: str = Field(default="active", max_length=32)
    is_featured: bool = False
    sort_order: int = Field(default=0, ge=0, le=10_000)


class CoachPackageOut(APIModel):
    id: str
    coach_profile_id: str
    title: str
    description: str = ""
    amount_minor: int
    currency: str
    billing_period: str
    duration_days: int | None = None
    includes: list[str] = Field(default_factory=list)
    delivery: str = "online"
    status: str = "active"
    is_featured: bool = False
    sort_order: int = 0
    created_at: datetime | None = None
    updated_at: datetime


class CoachPackagePage(APIModel):
    items: list[CoachPackageOut] = Field(default_factory=list)


class FeaturedPackageSummary(APIModel):
    id: str
    title: str
    amount_minor: int
    currency: str
    billing_period: str


class PackageInquireRequest(APIModel):
    message: str | None = Field(default=None, max_length=1000)


class PackageInquireOut(APIModel):
    thread_id: str
    peer_user_id: str
    package_id: str
    created: bool
