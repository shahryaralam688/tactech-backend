from pydantic import EmailStr, Field

from app.schemas.common import APIModel, TraineeProfileOut, TrainerProfileOut, UserPublic
from app.schemas.requests import RequestModel


class EditableProfileOut(APIModel):
    gender: str | None = None
    location: str | None = None
    height_cm: int | None = None
    weight_kg: float | None = None
    account_type: str = "Regular"
    avatar_url: str | None = None
    avatar_asset: str | None = None
    phone: str | None = None
    bio: str | None = None


class FullProfileOut(APIModel):
    user: UserPublic
    profile: EditableProfileOut
    trainer: TrainerProfileOut | None = None
    trainee: TraineeProfileOut | None = None


class UpdateProfileRequest(RequestModel):
    name: str | None = None
    email: EmailStr | None = None
    gender: str | None = None
    location: str | None = None
    height_cm: int | None = Field(default=None, ge=50, le=250)
    weight_kg: float | None = Field(default=None, gt=0)
    account_type: str | None = None
    avatar_asset: str | None = None
    phone: str | None = None
    bio: str | None = None


class AvatarOut(APIModel):
    avatar_url: str | None = None
    avatar_asset: str | None = None


class ChangePasswordRequest(RequestModel):
    current_password: str
    new_password: str = Field(min_length=6)


class CloseAccountRequest(RequestModel):
    password: str


class ForgotPasswordRequest(RequestModel):
    email: EmailStr
