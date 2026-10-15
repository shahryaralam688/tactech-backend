"""Join-request workflow DTOs (invite → pending → accept/reject)."""

from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import APIModel


class JoinPartyOut(APIModel):
    id: str
    name: str
    avatar_url: str | None = None
    email: str | None = None


class JoinRequestCreate(APIModel):
    invite_code: str = Field(min_length=1, max_length=32)
    message: str | None = Field(default=None, max_length=280)

    @field_validator("invite_code")
    @classmethod
    def _trim_code(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("message")
    @classmethod
    def _trim_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text[:280] if text else None


class JoinRequestOut(APIModel):
    id: str
    status: str
    invite_code: str
    message: str | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    trainer: JoinPartyOut | None = None
    trainee: JoinPartyOut | None = None


class JoinRequestStatusOut(APIModel):
    id: str
    status: str


class ActiveLinkOut(APIModel):
    trainer_id: str
    trainer: JoinPartyOut
    linked_at: datetime | None = None


class TraineeJoinStateOut(APIModel):
    active_link: ActiveLinkOut | None = None
    pending_request: JoinRequestOut | None = None


class RejectJoinRequest(APIModel):
    reason: str | None = Field(default=None, max_length=280)

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text[:280] if text else None
