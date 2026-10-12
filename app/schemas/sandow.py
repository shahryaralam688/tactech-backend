"""Live Sandow Score time-series (Profile chart)."""

from typing import Literal

from pydantic import AliasChoices, Field

from app.schemas.common import APIModel

SandowPeriod = Literal["week", "month"]
SandowRole = Literal["trainee", "trainer"]
SandowMode = Literal["workout_performance", "boost_analytics", "roster_performance"]


class SandowPointOut(APIModel):
    date: str
    label: str
    score: int = 0
    # boost_analytics extras
    views: int | None = None
    contacts: int | None = None
    impressions: int | None = None
    # roster_performance extras
    active_trainees: int | None = None
    sessions_logged: int | None = None


class SandowScoreOut(APIModel):
    role: SandowRole
    mode: SandowMode
    period: SandowPeriod
    title: str
    subtitle: str
    period_from: str = Field(
        validation_alias=AliasChoices("from", "periodFrom"),
        serialization_alias="from",
    )
    to: str
    summary_score: int = 0
    summary_label: str
    points: list[SandowPointOut] = Field(default_factory=list)
    # trainer modes
    boost_active: bool | None = None
    trainee_count: int | None = None
