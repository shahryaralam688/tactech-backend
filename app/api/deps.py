from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, RateLimitError, UnauthorizedError
from app.core.redis import RateLimiter, TokenDenylist, get_redis
from app.core.security import decode_token
from app.db.session import get_db
from app.services.auth_service import AuthService
from app.services.trainee_service import TraineeService
from app.services.assessment_service import AssessmentService
from app.services.trainer_service import TrainerService

Role = Literal["trainer", "trainee"]


@dataclass
class Principal:
    user_id: str
    role: Role
    trainer_id: str | None
    trainee_id: str | None
    jti: str | None


def get_auth_service(
    db: Annotated[Session, Depends(get_db)],
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(db, redis_client, settings)


def get_trainer_service(db: Annotated[Session, Depends(get_db)]) -> TrainerService:
    return TrainerService(db)


def get_trainee_service(db: Annotated[Session, Depends(get_db)]) -> TraineeService:
    return TraineeService(db)


def get_assessment_service(db: Annotated[Session, Depends(get_db)]) -> AssessmentService:
    return AssessmentService(db)


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("Authentication required.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise UnauthorizedError("Authentication required.")
    return token


def get_principal(
    settings: Annotated[Settings, Depends(get_settings)],
    redis_client: Annotated[Redis, Depends(get_redis)],
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    token = _bearer_token(authorization)
    payload = decode_token(token, settings)
    if payload.get("type") != "access":
        raise UnauthorizedError("Access token required.")
    jti = payload.get("jti")
    if jti and TokenDenylist(redis_client).is_revoked(jti):
        raise UnauthorizedError("Token has been revoked.")
    role = payload.get("role")
    if role not in {"trainer", "trainee"}:
        raise UnauthorizedError("Invalid token.")
    return Principal(
        user_id=payload["sub"],
        role=role,
        trainer_id=payload.get("trainerId"),
        trainee_id=payload.get("traineeId"),
        jti=jti,
    )


def require_trainer(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if principal.role != "trainer" or not principal.trainer_id:
        raise ForbiddenError("Trainer access required.")
    return principal


def require_trainee(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if principal.role != "trainee" or not principal.trainee_id:
        raise ForbiddenError("Trainee access required.")
    return principal


def enforce_auth_rate_limit(
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_forwarded_for: Annotated[str | None, Header()] = None,
) -> None:
    ip = (x_forwarded_for or "local").split(",")[0].strip()
    allowed = RateLimiter(redis_client).hit(
        f"auth:{ip}",
        settings.login_rate_limit,
        settings.login_rate_window_seconds,
    )
    if not allowed:
        raise RateLimitError()
