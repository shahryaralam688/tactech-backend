from datetime import datetime, timezone

from fastapi import Request, UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.security import hash_password, verify_password
from app.core.storage import (
    absolute_media_url,
    delete_avatar_object,
    delete_stored,
    read_image,
    save_avatar,
)
from app.db import models
from app.repositories.trainee import TraineeRepository
from app.repositories.trainer import TrainerRepository
from app.repositories.user import UserRepository
from app.schemas.mappers import trainee_out, trainer_out, user_public
from app.schemas.profile import (
    ALLOWED_GENDERS,
    AvatarOut,
    ChangePasswordRequest,
    EditableProfileOut,
    FullProfileOut,
    UpdateProfileRequest,
)
from app.services.user_gates import heal_completion_flags, maybe_mark_onboarding_completed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProfileService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.users = UserRepository(db)
        self.trainers = TrainerRepository(db)
        self.trainees = TraineeRepository(db)

    def get_profile(self, user_id: str, request: Request) -> FullProfileOut:
        user = self._require_user(user_id)
        heal_completion_flags(self.db, user)
        return self._to_out(user, request)

    def update_profile(self, user_id: str, payload: UpdateProfileRequest, request: Request) -> FullProfileOut:
        user = self._require_user(user_id)
        data = payload.model_dump(exclude_unset=True)

        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValidationAppError("Enter your name.", fields={"name": "required"})
            user.name = name

        if "email" in data and data.get("email") is not None:
            email = str(data["email"]).strip().lower()
            existing = self.users.get_by_email(email, include_deleted=True)
            if existing and existing.id != user.id:
                raise ConflictError(
                    "Email is already in use.",
                    fields={"email": "Email is already in use."},
                )
            user.email = email

        if "gender" in data:
            gender = (data.get("gender") or "").strip() or None
            if gender is not None and gender not in ALLOWED_GENDERS:
                raise ValidationAppError(
                    "Gender is not valid.",
                    fields={"gender": "Gender is not valid."},
                )
            user.gender = gender

        if "location" in data:
            location = (data.get("location") or "").strip() or None
            if location is not None and len(location) > 120:
                raise ValidationAppError(
                    "Location must be at most 120 characters.",
                    fields={"location": "too_long"},
                )
            user.location = location

        # accountType removed from iOS Personal Info — ignore if present.
        # Role is never changeable here.

        if "avatar_asset" in data:
            asset = (data.get("avatar_asset") or "").strip() or None
            user.avatar_asset = asset
            if asset:
                # Catalog avatar becomes primary; clear custom photo.
                delete_avatar_object(self.settings, user.avatar_url)
                user.avatar_url = None

        if "phone" in data:
            user.phone = (data.get("phone") or "").strip() or None

        if "bio" in data:
            bio = (data.get("bio") or "").strip() or None
            user.bio = bio
            if user.role == "trainer":
                trainer = self.trainers.get_by_user_id(user.id)
                if trainer is not None and bio is not None:
                    trainer.bio = bio

        trainee = self.trainees.get_by_user_id(user.id) if user.role == "trainee" else None
        if user.role == "trainee":
            if "height_cm" in data and data.get("height_cm") is not None:
                height = int(data["height_cm"])
                if height < 140 or height > 210:
                    raise ValidationAppError(
                        "Height must be between 140 and 210 cm.",
                        fields={"heightCm": "Height must be between 140 and 210."},
                    )
                user.height_cm = height
                if trainee is not None:
                    trainee.height_cm = height
            if "weight_kg" in data and data.get("weight_kg") is not None:
                weight = float(data["weight_kg"])
                if weight < 35 or weight > 180:
                    raise ValidationAppError(
                        "Weight must be between 35 and 180 kg.",
                        fields={"weightKg": "Weight must be between 35 and 180."},
                    )
                user.weight_kg = weight
                if trainee is not None:
                    trainee.weight_kg = weight
        # Trainers: ignore height/weight even if sent.

        trainer_row = self.trainers.get_by_user_id(user.id) if user.role == "trainer" else None
        maybe_mark_onboarding_completed(self.db, user, trainer=trainer_row, trainee=trainee)
        self.db.flush()
        return self._to_out(user, request)

    async def upload_avatar(self, user_id: str, file: UploadFile, request: Request) -> AvatarOut:
        user = self._require_user(user_id)
        data, extension = await read_image(
            file,
            self.settings,
            max_bytes=min(self.settings.max_upload_bytes, 5 * 1024 * 1024),
        )
        old = user.avatar_url
        # Unique key per upload (cache-bust). Prefer absolute CDN URL when configured.
        stored = save_avatar(
            self.settings, user_id=user.id, data=data, extension=extension
        )
        user.avatar_url = stored
        user.avatar_asset = None
        self.db.flush()
        # Best-effort: remove previous object after new key is committed to row
        if old and old != stored:
            delete_avatar_object(self.settings, old)
        abs_url = absolute_media_url(request, self.settings, stored)
        out = self._to_out(user, request)
        return AvatarOut(
            avatar_url=abs_url,
            avatar_asset=None,
            user=out.user,
            profile=out.profile,
        )

    def delete_avatar(self, user_id: str) -> None:
        user = self._require_user(user_id)
        delete_avatar_object(self.settings, user.avatar_url)
        user.avatar_url = None
        # Restore default catalog when no asset left (iOS initials still work if null).
        if not (user.avatar_asset or "").strip():
            user.avatar_asset = (
                self.settings.default_avatar_asset or "Avatar_01_Color"
            ).strip() or "Avatar_01_Color"

    def change_password(self, user_id: str, payload: ChangePasswordRequest) -> None:
        user = self._require_user(user_id)
        if not verify_password(payload.current_password, user.password_hash):
            raise ValidationAppError(
                "Current password is incorrect.",
                fields={"currentPassword": "Current password is incorrect."},
            )
        if len(payload.new_password) < 6:
            raise ValidationAppError(
                "Password must be at least 6 characters.",
                fields={"newPassword": "Password must be at least 6 characters."},
            )
        if payload.current_password == payload.new_password:
            raise ValidationAppError("Choose a different password.")
        user.password_hash = hash_password(payload.new_password)
        # Refresh tokens are not rotated on password change.

    def close_account(self, user_id: str, password: str) -> None:
        user = self._require_user(user_id)
        if not verify_password(password, user.password_hash):
            raise ValidationAppError("Current password is incorrect.")
        user.deleted_at = _utc_now()

    def _require_user(self, user_id: str) -> models.User:
        user = self.users.get_active(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user

    def _to_out(self, user: models.User, request: Request) -> FullProfileOut:
        trainer = self.trainers.get_by_user_id(user.id) if user.role == "trainer" else None
        trainee = self.trainees.get_by_user_id(user.id) if user.role == "trainee" else None
        height = user.height_cm
        weight = user.weight_kg
        if trainee is not None:
            height = height if height is not None else trainee.height_cm
            weight = weight if weight is not None else trainee.weight_kg
        bio = user.bio
        if bio is None and trainer is not None:
            bio = trainer.bio
        return FullProfileOut(
            user=user_public(user, request=request, settings=self.settings),
            profile=EditableProfileOut(
                gender=user.gender,
                location=user.location,
                height_cm=height,
                weight_kg=weight,
                account_type=user.account_type or None,
                avatar_url=absolute_media_url(request, self.settings, user.avatar_url),
                avatar_asset=user.avatar_asset,
                phone=user.phone,
                bio=bio,
            ),
            trainer=trainer_out(trainer) if trainer else None,
            trainee=(
                trainee_out(trainee, gender=user.gender, location=user.location) if trainee else None
            ),
            assessment_completed=bool(user.assessment_completed),
            onboarding_completed=bool(user.onboarding_completed),
        )
