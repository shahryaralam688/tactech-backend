from datetime import datetime, timezone

from fastapi import Request, UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, InvalidCredentialsError, NotFoundError, ValidationAppError
from app.core.security import hash_password, verify_password
from app.core.storage import absolute_media_url, delete_stored, read_image, save_bytes
from app.db import models
from app.repositories.trainee import TraineeRepository
from app.repositories.trainer import TrainerRepository
from app.repositories.user import UserRepository
from app.schemas.mappers import trainee_out, trainer_out, user_public
from app.schemas.profile import (
    AvatarOut,
    ChangePasswordRequest,
    EditableProfileOut,
    FullProfileOut,
    UpdateProfileRequest,
)


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
        return self._to_out(user, request)

    def update_profile(self, user_id: str, payload: UpdateProfileRequest, request: Request) -> FullProfileOut:
        user = self._require_user(user_id)
        if payload.name is not None:
            name = payload.name.strip()
            if not name:
                raise ValidationAppError("Enter your name.", fields={"name": "required"})
            user.name = name
        if payload.email is not None:
            email = str(payload.email).strip().lower()
            existing = self.users.get_by_email(email, include_deleted=True)
            if existing and existing.id != user.id:
                raise ConflictError(
                    "An account with this email already exists.",
                    fields={"email": "already registered"},
                )
            user.email = email
        if payload.gender is not None:
            user.gender = payload.gender.strip() or None
        if payload.location is not None:
            user.location = payload.location.strip() or None
        if payload.height_cm is not None:
            user.height_cm = payload.height_cm
        if payload.weight_kg is not None:
            user.weight_kg = payload.weight_kg
        if payload.account_type is not None:
            user.account_type = payload.account_type.strip() or "Regular"
        if payload.avatar_asset is not None:
            user.avatar_asset = payload.avatar_asset.strip() or None
        if payload.phone is not None:
            user.phone = payload.phone.strip() or None
        if payload.bio is not None:
            user.bio = payload.bio.strip() or None

        if user.role == "trainee":
            trainee = self.trainees.get_by_user_id(user.id)
            if trainee is not None:
                if payload.height_cm is not None:
                    trainee.height_cm = payload.height_cm
                if payload.weight_kg is not None:
                    trainee.weight_kg = payload.weight_kg
        if user.role == "trainer" and payload.bio is not None:
            trainer = self.trainers.get_by_user_id(user.id)
            if trainer is not None:
                trainer.bio = payload.bio.strip()

        return self._to_out(user, request)

    async def upload_avatar(self, user_id: str, file: UploadFile, request: Request) -> AvatarOut:
        user = self._require_user(user_id)
        data, extension = await read_image(file, self.settings)
        delete_stored(self.settings, user.avatar_url)
        stored = save_bytes(self.settings, "avatars", data, extension)
        user.avatar_url = stored
        user.avatar_asset = None
        return AvatarOut(
            avatar_url=absolute_media_url(request, self.settings, stored),
            avatar_asset=None,
        )

    def delete_avatar(self, user_id: str) -> None:
        user = self._require_user(user_id)
        delete_stored(self.settings, user.avatar_url)
        user.avatar_url = None

    def change_password(self, user_id: str, payload: ChangePasswordRequest) -> None:
        user = self._require_user(user_id)
        if not verify_password(payload.current_password, user.password_hash):
            raise InvalidCredentialsError()
        if len(payload.new_password) < 6:
            raise ValidationAppError("Password must be at least 6 characters.")
        if payload.current_password == payload.new_password:
            raise ValidationAppError("Choose a different password.")
        user.password_hash = hash_password(payload.new_password)

    def close_account(self, user_id: str, password: str) -> None:
        user = self._require_user(user_id)
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
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
            user=user_public(user),
            profile=EditableProfileOut(
                gender=user.gender,
                location=user.location,
                height_cm=height,
                weight_kg=weight,
                account_type=user.account_type or "Regular",
                avatar_url=absolute_media_url(request, self.settings, user.avatar_url),
                avatar_asset=user.avatar_asset,
                phone=user.phone,
                bio=bio,
            ),
            trainer=trainer_out(trainer) if trainer else None,
            trainee=trainee_out(trainee) if trainee else None,
        )
