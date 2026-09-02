import random
from datetime import datetime, timezone
from uuid import uuid4

from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import InvalidCredentialsError, UnauthorizedError, ValidationAppError
from app.core.redis import TokenDenylist
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.db import models
from app.repositories.trainer import TrainerRepository
from app.repositories.trainee import TraineeRepository
from app.repositories.user import UserRepository
from app.schemas.mappers import trainer_out, trainee_out, user_public
from app.schemas.responses import AuthResponse, MeResponse


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_invite_code(name: str, trainers: TrainerRepository) -> str:
    prefix = "".join(part[0] for part in name.split() if part).upper()[:2]
    if not prefix:
        prefix = "TT"
    for _ in range(20):
        code = f"TACT-{prefix}{random.randint(100, 999)}"
        if not trainers.invite_code_exists(code):
            return code
    return f"TACT-{prefix}{uuid4().hex[:3].upper()}"


class AuthService:
    def __init__(self, db: Session, redis_client: Redis, settings: Settings) -> None:
        self.users = UserRepository(db)
        self.trainers = TrainerRepository(db)
        self.trainees = TraineeRepository(db)
        self.denylist = TokenDenylist(redis_client)
        self.settings = settings

    def signup(
        self,
        *,
        name: str,
        email: str,
        password: str,
        role: str,
        invite_code: str | None,
    ) -> AuthResponse:
        normalized_name = name.strip()
        normalized_email = email.strip().lower()
        if not normalized_name:
            raise ValidationAppError("Enter your name.")
        if "@" not in normalized_email:
            raise ValidationAppError("Enter a valid email.")
        if len(password) < 6:
            raise ValidationAppError("Password must be at least 6 characters.")
        if role not in {"trainer", "trainee"}:
            raise ValidationAppError("Role must be trainer or trainee.")
        if self.users.get_by_email(normalized_email):
            raise ValidationAppError("An account with this email already exists.")

        user = models.User(
            id=str(uuid4()),
            name=normalized_name,
            email=normalized_email,
            password_hash=hash_password(password),
            role=role,
            created_at=_utc_now(),
        )
        self.users.add(user)

        trainer = None
        trainee = None
        if role == "trainer":
            trainer = models.TrainerProfile(
                id=str(uuid4()),
                user_id=user.id,
                invite_code=_make_invite_code(normalized_name, self.trainers),
                specialty="Strength & Conditioning",
                years_experience=3,
                bio="Helping athletes move better and get stronger.",
            )
            self.trainers.add(trainer)
        else:
            linked = None
            if invite_code:
                linked = self.trainers.get_by_invite_code(invite_code)
            trainee = models.TraineeProfile(
                id=str(uuid4()),
                user_id=user.id,
                trainer_id=linked.id if linked else None,
                goal="Build strength",
                height_cm=170,
                weight_kg=70,
                daily_calorie_target=2200,
            )
            self.trainees.add(trainee)

        return self._issue(user, trainer, trainee)

    def login(self, email: str, password: str) -> AuthResponse:
        user = self.users.get_by_email(email.strip().lower())
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
        trainer = self.trainers.get_by_user_id(user.id) if user.role == "trainer" else None
        trainee = self.trainees.get_by_user_id(user.id) if user.role == "trainee" else None
        return self._issue(user, trainer, trainee)

    def refresh(self, refresh_token: str) -> AuthResponse:
        payload = decode_token(refresh_token, self.settings)
        if payload.get("type") != "refresh":
            raise UnauthorizedError("Invalid refresh token.")
        jti = payload.get("jti")
        if not jti or self.denylist.is_revoked(jti):
            raise UnauthorizedError("Refresh token has been revoked.")
        user = self.users.get(payload["sub"])
        if user is None:
            raise UnauthorizedError("User no longer exists.")
        trainer = self.trainers.get_by_user_id(user.id) if user.role == "trainer" else None
        trainee = self.trainees.get_by_user_id(user.id) if user.role == "trainee" else None
        ttl = int(payload["exp"]) - int(_utc_now().timestamp())
        self.denylist.revoke(jti, ttl)
        return self._issue(user, trainer, trainee)

    def logout(self, refresh_token: str) -> None:
        payload = decode_token(refresh_token, self.settings)
        jti = payload.get("jti")
        if jti:
            ttl = int(payload.get("exp", 0)) - int(_utc_now().timestamp())
            self.denylist.revoke(jti, ttl)

    def me(self, user_id: str) -> MeResponse:
        user = self.users.get(user_id)
        if user is None:
            raise UnauthorizedError("User no longer exists.")
        trainer = self.trainers.get_by_user_id(user.id) if user.role == "trainer" else None
        trainee = self.trainees.get_by_user_id(user.id) if user.role == "trainee" else None
        return MeResponse(
            user=user_public(user),
            trainer=trainer_out(trainer) if trainer else None,
            trainee=trainee_out(trainee) if trainee else None,
        )

    def _issue(
        self,
        user: models.User,
        trainer: models.TrainerProfile | None,
        trainee: models.TraineeProfile | None,
    ) -> AuthResponse:
        access, _, _ = create_token(
            settings=self.settings,
            user_id=user.id,
            role=user.role,  # type: ignore[arg-type]
            trainer_id=trainer.id if trainer else None,
            trainee_id=trainee.id if trainee else None,
            token_type="access",
        )
        refresh, _, _ = create_token(
            settings=self.settings,
            user_id=user.id,
            role=user.role,  # type: ignore[arg-type]
            trainer_id=trainer.id if trainer else None,
            trainee_id=trainee.id if trainee else None,
            token_type="refresh",
        )
        return AuthResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=self.settings.access_token_expire_minutes * 60,
            user=user_public(user),
            trainer=trainer_out(trainer) if trainer else None,
            trainee=trainee_out(trainee) if trainee else None,
        )
