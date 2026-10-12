from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, UploadFile, File, status

from app.api.deps import (
    Principal,
    get_ai_billing_service,
    get_analytics_service,
    get_auth_service,
    get_billing_service,
    get_discovery_service,
    get_entitlement_service,
    get_follow_service,
    get_preference_service,
    get_principal,
    get_profile_service,
    get_push_service,
    get_sandow_service,
    get_trainer_service,
    get_trainee_service,
    get_package_service,
    get_verification_service,
    require_trainee,
    require_trainer,
)
from app.schemas.common import TraineeProfileOut
from app.schemas.billing import MeAiOut, MeBoostOut
from app.schemas.analytics import CoachAnalyticsOut, CoachAnalyticsSummaryOut
from app.schemas.sandow import SandowScoreOut
from app.schemas.discovery import (
    CoachProfileOut,
    CoachProfilePatchRequest,
    CoachProfileUpdateRequest,
    EntitlementsOut,
)
from app.schemas.follows import CoachFollowOut, TrainerFollowPage
from app.services.follow_service import FollowService
from app.schemas.packages import CoachPackageOut, CoachPackagePage, CoachPackageUpsertRequest
from app.schemas.verification import (
    MeCoachVerificationOut,
    VerifyApplicationCreateRequest,
    VerifyApplicationOut,
    VerifyCancelOut,
    VerifyUploadOut,
    VerifyUploadRequest,
)
from app.schemas.notifications import (
    AppNotificationPage,
    NotificationDeleteRequest,
    NotificationReadRequest,
    NotificationUnreadCountOut,
    PushTokenDeleteRequest,
    PushTokenOut,
    PushTokenRegisterRequest,
)
from app.schemas.preferences import (
    AppFeedbackCreated,
    AppFeedbackOut,
    AppFeedbackRequest,
    LanguagePreferences,
    NotificationPreferences,
    SecurityPreferences,
)
from app.schemas.profile import (
    AvatarOut,
    ChangePasswordRequest,
    CloseAccountRequest,
    FullProfileOut,
    UpdateProfileRequest,
)
from app.schemas.requests import UpdateTraineeProfileRequest, UpdateTrainerProfileRequest
from app.schemas.responses import MeResponse, TrainerPublic
from app.services.ai_billing_service import AiBillingService
from app.services.auth_service import AuthService
from app.services.billing_service import BillingService
from app.core.config import get_settings
from app.core.storage import public_base
from app.services.analytics_service import AnalyticsService
from app.services.discovery_service import DiscoveryService
from app.services.entitlement_service import EntitlementService
from app.services.package_service import PackageService
from app.services.sandow_service import SandowService
from app.services.verification_service import VerificationService
from app.services.preference_service import PreferenceService
from app.services.profile_service import ProfileService
from app.services.push_service import PushService
from app.services.trainee_service import TraineeService
from app.services.trainer_service import TrainerService

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
def me(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MeResponse:
    return service.me(principal.user_id)


@router.get("/me/profile", response_model=FullProfileOut)
def get_profile(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> FullProfileOut:
    return service.get_profile(principal.user_id, request)


@router.patch("/me/profile", response_model=FullProfileOut)
def update_profile(
    payload: UpdateProfileRequest,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> FullProfileOut:
    return service.update_profile(principal.user_id, payload, request)


@router.post("/me/avatar", response_model=AvatarOut)
async def upload_avatar(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
    file: Annotated[UploadFile, File()],
) -> AvatarOut:
    return await service.upload_avatar(principal.user_id, file, request)


@router.delete("/me/avatar", status_code=status.HTTP_204_NO_CONTENT)
def delete_avatar(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> None:
    service.delete_avatar(principal.user_id)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> None:
    service.change_password(principal.user_id, payload)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def close_account(
    payload: CloseAccountRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> None:
    service.close_account(principal.user_id, payload.password)


@router.get("/me/preferences/notifications", response_model=NotificationPreferences)
def get_notification_preferences(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PreferenceService, Depends(get_preference_service)],
) -> NotificationPreferences:
    return service.notifications(principal.user_id)


@router.put("/me/preferences/notifications", response_model=NotificationPreferences)
def put_notification_preferences(
    payload: NotificationPreferences,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PreferenceService, Depends(get_preference_service)],
) -> NotificationPreferences:
    return service.save_notifications(principal.user_id, payload)


@router.post("/me/push-tokens", response_model=PushTokenOut, status_code=status.HTTP_201_CREATED)
def register_push_token(
    payload: PushTokenRegisterRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PushService, Depends(get_push_service)],
) -> PushTokenOut:
    return service.register_token(
        principal.user_id,
        token=payload.token,
        platform=payload.platform,
        device_name=payload.device_name,
        app_version=payload.app_version,
    )


@router.get("/me/push-tokens", response_model=list[PushTokenOut])
def list_push_tokens(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PushService, Depends(get_push_service)],
) -> list[PushTokenOut]:
    return service.list_tokens(principal.user_id)


@router.delete("/me/push-tokens", status_code=status.HTTP_204_NO_CONTENT)
def delete_push_token(
    payload: PushTokenDeleteRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PushService, Depends(get_push_service)],
) -> None:
    service.unregister_token(principal.user_id, payload.token)


@router.get("/me/notifications", response_model=AppNotificationPage)
def list_notifications(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PushService, Depends(get_push_service)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> AppNotificationPage:
    return service.list_inbox(principal.user_id, cursor=cursor, limit=limit)


@router.get("/me/notifications/unread-count", response_model=NotificationUnreadCountOut)
def notifications_unread_count(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PushService, Depends(get_push_service)],
) -> NotificationUnreadCountOut:
    return service.unread_count(principal.user_id)


@router.post("/me/notifications/read", response_model=NotificationUnreadCountOut)
def mark_notifications_read(
    payload: NotificationReadRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PushService, Depends(get_push_service)],
) -> NotificationUnreadCountOut:
    return service.mark_read(principal.user_id, payload.notification_id)


@router.post("/me/notifications/delete", response_model=NotificationUnreadCountOut)
def delete_notifications(
    payload: NotificationDeleteRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PushService, Depends(get_push_service)],
) -> NotificationUnreadCountOut:
    """Delete one notification, or clear all when notificationId is null/omitted."""
    return service.delete(principal.user_id, payload.notification_id)


@router.get("/me/preferences/security", response_model=SecurityPreferences)
def get_security_preferences(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PreferenceService, Depends(get_preference_service)],
) -> SecurityPreferences:
    return service.security(principal.user_id)


@router.put("/me/preferences/security", response_model=SecurityPreferences)
def put_security_preferences(
    payload: SecurityPreferences,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PreferenceService, Depends(get_preference_service)],
) -> SecurityPreferences:
    return service.save_security(principal.user_id, payload)


@router.get("/me/preferences/language", response_model=LanguagePreferences)
def get_language_preferences(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PreferenceService, Depends(get_preference_service)],
) -> LanguagePreferences:
    return service.language(principal.user_id)


@router.put("/me/preferences/language", response_model=LanguagePreferences)
def put_language_preferences(
    payload: LanguagePreferences,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PreferenceService, Depends(get_preference_service)],
) -> LanguagePreferences:
    return service.save_language(principal.user_id, payload)


@router.post("/me/app-feedback", response_model=AppFeedbackCreated, status_code=status.HTTP_201_CREATED)
def submit_app_feedback(
    payload: AppFeedbackRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PreferenceService, Depends(get_preference_service)],
) -> AppFeedbackCreated:
    return service.submit_feedback(principal.user_id, payload)


@router.get("/me/app-feedback", response_model=list[AppFeedbackOut])
def list_app_feedback(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PreferenceService, Depends(get_preference_service)],
) -> list[AppFeedbackOut]:
    return service.list_feedback(principal.user_id)


@router.get("/me/entitlements", response_model=EntitlementsOut)
def get_entitlements(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> EntitlementsOut:
    return service.get_entitlements(principal.user_id)


@router.get("/me/boost", response_model=MeBoostOut)
def get_my_boost(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> MeBoostOut:
    return service.get_me_boost(principal)


@router.get("/me/ai", response_model=MeAiOut)
def get_my_ai(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AiBillingService, Depends(get_ai_billing_service)],
) -> MeAiOut:
    return service.get_me_ai(principal.user_id)


@router.get(
    "/me/sandow-score",
    response_model=SandowScoreOut,
    response_model_exclude_none=True,
)
def get_my_sandow_score(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[SandowService, Depends(get_sandow_service)],
    period: Annotated[str, Query()] = "week",
) -> SandowScoreOut:
    """Live Profile Sandow Score series (trainee workout, trainer boost or roster)."""
    return service.get_series(principal, period=period)


@router.get("/me/coach-analytics", response_model=CoachAnalyticsOut)
def get_my_coach_analytics(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    period_days: Annotated[int, Query(alias="periodDays")] = 30,
) -> CoachAnalyticsOut:
    return service.get_analytics(principal, period_days=period_days, include_series=True)  # type: ignore[return-value]


@router.get("/me/coach-analytics/summary", response_model=CoachAnalyticsSummaryOut)
def get_my_coach_analytics_summary(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    period_days: Annotated[int, Query(alias="periodDays")] = 30,
) -> CoachAnalyticsSummaryOut:
    return service.get_analytics(principal, period_days=period_days, include_series=False)  # type: ignore[return-value]


@router.get("/me/coach-verification", response_model=MeCoachVerificationOut)
def get_my_coach_verification(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> MeCoachVerificationOut:
    return service.get_me(principal)


@router.post("/me/coach-verification/uploads", response_model=VerifyUploadOut)
def create_verification_upload(
    payload: VerifyUploadRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> VerifyUploadOut:
    base = public_base(request, get_settings())
    return service.create_upload_slot(principal, payload, public_base=base)


@router.put("/me/coach-verification/uploads/{upload_id}")
async def put_verification_upload(
    upload_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> dict:
    data = await request.body()
    return service.put_upload_bytes(principal, upload_id, data)


@router.post(
    "/me/coach-verification/applications",
    response_model=VerifyApplicationOut,
    status_code=status.HTTP_201_CREATED,
)
def submit_verification_application(
    payload: VerifyApplicationCreateRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> VerifyApplicationOut:
    return service.submit(principal, payload)


@router.post("/me/coach-verification/cancel", response_model=VerifyCancelOut)
def cancel_verification_application(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> VerifyCancelOut:
    return service.cancel(principal)


@router.get("/me/coach-packages", response_model=CoachPackagePage)
def list_my_coach_packages(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[PackageService, Depends(get_package_service)],
) -> CoachPackagePage:
    return service.list_mine(principal)


@router.post(
    "/me/coach-packages",
    response_model=CoachPackageOut,
    status_code=status.HTTP_201_CREATED,
)
def create_coach_package(
    payload: CoachPackageUpsertRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[PackageService, Depends(get_package_service)],
) -> CoachPackageOut:
    return service.create(principal, payload)


@router.put("/me/coach-packages/{package_id}", response_model=CoachPackageOut)
def update_coach_package(
    package_id: str,
    payload: CoachPackageUpsertRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[PackageService, Depends(get_package_service)],
) -> CoachPackageOut:
    return service.update(principal, package_id, payload)


@router.post("/me/coach-packages/{package_id}/archive", response_model=CoachPackageOut)
def archive_coach_package(
    package_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[PackageService, Depends(get_package_service)],
) -> CoachPackageOut:
    return service.archive(principal, package_id)


@router.get("/me/coach-profile", response_model=CoachProfileOut)
def get_my_coach_profile(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> CoachProfileOut:
    return service.get_or_create_my_profile(principal)


@router.put("/me/coach-profile", response_model=CoachProfileOut)
def put_my_coach_profile(
    payload: CoachProfileUpdateRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> CoachProfileOut:
    return service.update_my_profile(principal, payload)


@router.patch("/me/coach-profile", response_model=CoachProfileOut)
def patch_my_coach_profile(
    payload: CoachProfilePatchRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> CoachProfileOut:
    """Partial update (e.g. `{ \"followMode\": \"auto_accept\" }`)."""
    return service.patch_my_profile(principal, payload)


@router.get("/me/coach-follows", response_model=TrainerFollowPage)
def list_coach_follows(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[FollowService, Depends(get_follow_service)],
    status: Annotated[str | None, Query()] = "pending",
) -> TrainerFollowPage:
    return service.list_for_trainer(principal, status=status)


@router.post("/me/coach-follows/{follow_id}/accept", response_model=CoachFollowOut)
def accept_coach_follow(
    follow_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[FollowService, Depends(get_follow_service)],
) -> CoachFollowOut:
    return service.accept(principal, follow_id)


@router.post("/me/coach-follows/{follow_id}/decline", response_model=CoachFollowOut)
def decline_coach_follow(
    follow_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[FollowService, Depends(get_follow_service)],
) -> CoachFollowOut:
    return service.decline(principal, follow_id)


@router.post("/me/coach-follows/{follow_id}/end", response_model=CoachFollowOut)
def end_coach_follow_trainer(
    follow_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[FollowService, Depends(get_follow_service)],
) -> CoachFollowOut:
    return service.end_as_trainer(principal, follow_id)


@router.post("/me/coach-follow/end", response_model=CoachFollowOut)
def end_coach_follow_trainee(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[FollowService, Depends(get_follow_service)],
) -> CoachFollowOut:
    return service.end_mine(principal)


@router.patch("/me/trainer", response_model=TrainerPublic)
def update_trainer_profile(
    payload: UpdateTrainerProfileRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> TrainerPublic:
    from app.core.exceptions import ForbiddenError

    if principal.role != "trainer" or not principal.trainer_id:
        raise ForbiddenError("Trainer access required.")
    return service.update_profile(principal.trainer_id, payload)


@router.patch("/me/trainee", response_model=TraineeProfileOut)
def update_trainee_profile(
    payload: UpdateTraineeProfileRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> TraineeProfileOut:
    from app.core.exceptions import ForbiddenError

    if principal.role != "trainee" or not principal.trainee_id:
        raise ForbiddenError("Trainee access required.")
    return service.update_profile(principal.trainee_id, payload)
