from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, RateLimitError, UnauthorizedError
from app.core.redis import RateLimiter, TokenDenylist, get_redis
from app.core.security import decode_token
from app.db import models
from app.db.session import get_db
from app.services.auth_service import AuthService
from app.services.assessment_service import AssessmentService
from app.services.coach_service import CoachService
from app.services.content_service import ContentService
from app.services.preference_service import PreferenceService
from app.services.profile_service import ProfileService
from app.services.support_service import SupportService
from app.services.template_service import TemplateService
from app.services.trainee_service import TraineeService
from app.services.trainer_service import TrainerService
from app.services.push_service import PushService
from app.services.ai_access import AiAccessService
from app.services.ai_billing_service import AiBillingService
from app.services.billing_service import BillingService
from app.services.discovery_service import DiscoveryService
from app.services.entitlement_service import EntitlementService
from app.services.review_service import ReviewService
from app.services.analytics_service import AnalyticsService
from app.services.sandow_service import SandowService
from app.services.verification_service import VerificationService
from app.services.package_service import PackageService
from app.services.follow_service import FollowService
from app.realtime.chat_hub import chat_hub

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


def get_profile_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProfileService:
    return ProfileService(db, settings)


def get_template_service(db: Annotated[Session, Depends(get_db)]) -> TemplateService:
    return TemplateService(db)


def get_preference_service(db: Annotated[Session, Depends(get_db)]) -> PreferenceService:
    return PreferenceService(db)


def get_push_service(db: Annotated[Session, Depends(get_db)]) -> PushService:
    return PushService(db, hub=chat_hub)


def get_support_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SupportService:
    return SupportService(db, settings)


def get_content_service() -> ContentService:
    return ContentService()


def get_coach_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CoachService:
    return CoachService(db, settings)


def get_entitlement_service(db: Annotated[Session, Depends(get_db)]) -> EntitlementService:
    return EntitlementService(db)


def get_discovery_service(db: Annotated[Session, Depends(get_db)]) -> DiscoveryService:
    return DiscoveryService(db)


def get_review_service(db: Annotated[Session, Depends(get_db)]) -> ReviewService:
    return ReviewService(db)


def get_analytics_service(db: Annotated[Session, Depends(get_db)]) -> AnalyticsService:
    return AnalyticsService(db)


def get_sandow_service(db: Annotated[Session, Depends(get_db)]) -> SandowService:
    return SandowService(db)


def get_verification_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> VerificationService:
    return VerificationService(db, settings, redis_client)


def get_package_service(db: Annotated[Session, Depends(get_db)]) -> PackageService:
    return PackageService(db)


def get_follow_service(db: Annotated[Session, Depends(get_db)]) -> FollowService:
    return FollowService(db)


def require_admin_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_admin_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None,
) -> str:
    """Staging/admin review: header must match ADMIN_API_KEY. Returns reviewer label."""
    expected = (settings.admin_api_key or "").strip()
    if not expected:
        raise ForbiddenError("Admin API is not configured (ADMIN_API_KEY).")
    if not x_admin_key or x_admin_key.strip() != expected:
        raise ForbiddenError("Invalid admin key.")
    return "admin-key"


def get_billing_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BillingService:
    return BillingService(db, settings)


def get_ai_billing_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AiBillingService:
    return AiBillingService(db, settings)


def get_ai_access_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AiAccessService:
    return AiAccessService(db, settings)


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
    db: Annotated[Session, Depends(get_db)],
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
    user = db.get(models.User, payload["sub"])
    if user is None or user.deleted_at is not None:
        raise UnauthorizedError("User no longer exists.")
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


def require_ai_access(
    principal: Annotated[Principal, Depends(get_principal)],
    access: Annotated[AiAccessService, Depends(get_ai_access_service)],
) -> Principal:
    """402 AI_REQUIRED when no subscription and no free tease left. Consumes tease if used."""
    access.assert_ai_access(principal.user_id, consume_tease=True)
    return principal


def enforce_auth_rate_limit(
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_forwarded_for: Annotated[str | None, Header()] = None,
) -> None:
    ip = (x_forwarded_for or "local").split(",")[0].strip()
    allowed, retry_after = RateLimiter(redis_client).check(
        f"auth:{ip}",
        settings.login_rate_limit,
        settings.login_rate_window_seconds,
    )
    if not allowed:
        raise RateLimitError(retry_after=retry_after)


def _enforce_user_rate_limit(
    *,
    redis_client: Redis,
    settings: Settings,
    principal: Principal,
    action: str,
    limit: int,
    detail: str,
) -> None:
    allowed, retry_after = RateLimiter(redis_client).check(
        f"{action}:{principal.user_id}",
        limit,
        settings.coach_rate_window_seconds,
    )
    if not allowed:
        raise RateLimitError(detail, retry_after=retry_after)


def enforce_coach_chat_rate_limit(
    principal: Annotated[Principal, Depends(get_principal)],
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    _enforce_user_rate_limit(
        redis_client=redis_client,
        settings=settings,
        principal=principal,
        action="coach:chat",
        limit=settings.coach_chat_rate_limit,
        detail="Too many coach messages. Wait a moment, then try again.",
    )


def enforce_coach_image_rate_limit(
    principal: Annotated[Principal, Depends(get_principal)],
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    _enforce_user_rate_limit(
        redis_client=redis_client,
        settings=settings,
        principal=principal,
        action="coach:image",
        limit=settings.coach_image_rate_limit,
        detail="Too many photo analyses. Wait a moment, then try again.",
    )


def enforce_coach_voice_rate_limit(
    principal: Annotated[Principal, Depends(get_principal)],
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    _enforce_user_rate_limit(
        redis_client=redis_client,
        settings=settings,
        principal=principal,
        action="coach:voice",
        limit=settings.coach_voice_rate_limit,
        detail="Too many voice turns. Wait a moment, then try again.",
    )


def enforce_coach_rtc_rate_limit(
    principal: Annotated[Principal, Depends(get_principal)],
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    _enforce_user_rate_limit(
        redis_client=redis_client,
        settings=settings,
        principal=principal,
        action="coach:rtc",
        limit=settings.coach_rtc_rate_limit,
        detail="Too many call sessions. Wait a moment, then try again.",
    )


def enforce_chat_rate_limit(
    principal: Annotated[Principal, Depends(get_principal)],
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    allowed, retry_after = RateLimiter(redis_client).check(
        f"chat:msg:{principal.user_id}",
        settings.chat_rate_limit,
        settings.chat_rate_window_seconds,
    )
    if not allowed:
        raise RateLimitError(
            "Too many messages. Wait a moment, then try again.",
            retry_after=retry_after,
        )


def enforce_chat_media_rate_limit(
    principal: Annotated[Principal, Depends(get_principal)],
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    allowed, retry_after = RateLimiter(redis_client).check(
        f"chat:media:{principal.user_id}",
        settings.chat_media_rate_limit,
        settings.chat_rate_window_seconds,
    )
    if not allowed:
        raise RateLimitError(
            "Too many media uploads. Wait a moment, then try again.",
            retry_after=retry_after,
        )


def enforce_chat_rtc_rate_limit(
    principal: Annotated[Principal, Depends(get_principal)],
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    allowed, retry_after = RateLimiter(redis_client).check(
        f"chat:rtc:{principal.user_id}",
        settings.chat_rtc_rate_limit,
        settings.chat_rate_window_seconds,
    )
    if not allowed:
        raise RateLimitError(
            "Too many call sessions. Wait a moment, then try again.",
            retry_after=retry_after,
        )
