from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError

Role = Literal["trainer", "trainee"]
TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_token(
    *,
    settings: Settings,
    user_id: str,
    role: Role,
    trainer_id: str | None,
    trainee_id: str | None,
    token_type: TokenType,
) -> tuple[str, str, datetime]:
    jti = str(uuid4())
    issued = _now()
    if token_type == "access":
        expires = issued + timedelta(minutes=settings.access_token_expire_minutes)
    else:
        expires = issued + timedelta(days=settings.refresh_token_expire_days)

    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "type": token_type,
        "jti": jti,
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    if trainer_id:
        payload["trainerId"] = trainer_id
    if trainee_id:
        payload["traineeId"] = trainee_id

    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti, expires


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid token.") from exc
