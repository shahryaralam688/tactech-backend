"""Trainer discovery analytics DTOs (Phase 6). No viewer PII."""

from datetime import datetime

from pydantic import AliasChoices, Field

from app.schemas.common import APIModel


class AnalyticsTotalsOut(APIModel):
    views: int = 0
    unique_viewers: int = 0
    impressions: int = 0
    contacts: int = 0
    contacts_created: int = 0
    rating_avg: float | None = None
    rating_count: int = 0
    boost_active_days: int = 0


class AnalyticsDayOut(APIModel):
    date: str
    views: int = 0
    unique_viewers: int = 0
    impressions: int = 0
    contacts: int = 0


class AnalyticsBoostOut(APIModel):
    active_now: bool = False
    ends_at: datetime | None = None


class CoachAnalyticsOut(APIModel):
    coach_profile_id: str
    period_days: int
    period_from: datetime = Field(
        validation_alias=AliasChoices("from", "periodFrom"),
        serialization_alias="from",
    )
    to: datetime
    totals: AnalyticsTotalsOut
    series: list[AnalyticsDayOut] = Field(default_factory=list)
    boost: AnalyticsBoostOut = Field(default_factory=AnalyticsBoostOut)


class CoachAnalyticsSummaryOut(APIModel):
    coach_profile_id: str
    period_days: int
    period_from: datetime = Field(
        validation_alias=AliasChoices("from", "periodFrom"),
        serialization_alias="from",
    )
    to: datetime
    totals: AnalyticsTotalsOut
    boost: AnalyticsBoostOut = Field(default_factory=AnalyticsBoostOut)


class ImpressionsRequest(APIModel):
    coach_profile_ids: list[str] = Field(default_factory=list, max_length=50)
    source: str = Field(default="discover_list", max_length=64)


class ImpressionsOut(APIModel):
    recorded: int = 0
