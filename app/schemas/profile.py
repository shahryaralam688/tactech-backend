from pydantic import EmailStr, Field

from app.schemas.common import APIModel, TraineeProfileOut, TrainerProfileOut, UserPublic
from app.schemas.requests import RequestModel

ALLOWED_GENDERS = (
    "Male",
    "Female",
    "Non-binary",
    "Trans Female",
    "Trans Male",
)


class EditableProfileOut(APIModel):
    gender: str | None = None
    location: str | None = None
    height_cm: int | None = None
    weight_kg: float | None = None
    account_type: str | None = None
    avatar_url: str | None = None
    avatar_asset: str | None = None
    phone: str | None = None
    bio: str | None = None


class FullProfileOut(APIModel):
    user: UserPublic
    profile: EditableProfileOut
    trainer: TrainerProfileOut | None = None
    trainee: TraineeProfileOut | None = None
    assessment_completed: bool = False
    onboarding_completed: bool = False


class UpdateProfileRequest(RequestModel):
    name: str | None = None
    email: EmailStr | None = None
    gender: str | None = None
    location: str | None = Field(default=None, max_length=120)
    height_cm: int | None = None
    weight_kg: float | None = None
    # Ignored — removed from iOS Personal Info; kept for backward-compatible clients.
    account_type: str | None = None
    avatar_asset: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=64)
    bio: str | None = None


class AvatarOut(APIModel):
    avatar_url: str | None = None
    avatar_asset: str | None = None
    # Enough for iOS to refresh without a second GET /me
    user: UserPublic | None = None
    profile: EditableProfileOut | None = None


class ChangePasswordRequest(RequestModel):
    current_password: str
    new_password: str = Field(min_length=1)


class CloseAccountRequest(RequestModel):
    password: str


class ForgotPasswordRequest(RequestModel):
    email: EmailStr
