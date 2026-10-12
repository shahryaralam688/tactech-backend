"""Coach follow / hire DTOs (Phase 9). Free — no payment."""

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class FollowCreateRequest(APIModel):
    note: str | None = Field(default=None, max_length=500)
    package_id: str | None = Field(default=None, max_length=64)


class CoachFollowOut(APIModel):
    id: str
    coach_profile_id: str
    trainer_user_id: str
    trainee_user_id: str
    status: str
    package_id: str | None = None
    package_title: str | None = None
    note: str | None = None
    thread_id: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    accepted_at: datetime | None = None
    ended_at: datetime | None = None


class FollowStateOut(APIModel):
    status: str = "none"  # none | pending | active | declined | ended
    follow: CoachFollowOut | None = None


class TrainerFollowItemOut(APIModel):
    id: str
    coach_profile_id: str
    trainee_user_id: str
    trainee_name: str
    trainee_avatar_url: str | None = None
    status: str
    package_id: str | None = None
    package_title: str | None = None
    note: str | None = None
    thread_id: str | None = None
    created_at: datetime
    accepted_at: datetime | None = None


class TrainerFollowPage(APIModel):
    items: list[TrainerFollowItemOut] = Field(default_factory=list)
