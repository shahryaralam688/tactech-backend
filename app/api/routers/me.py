from typing import Annotated

from fastapi import APIRouter, Depends, Request, UploadFile, File, status

from app.api.deps import (
    Principal,
    get_auth_service,
    get_preference_service,
    get_principal,
    get_profile_service,
    get_trainer_service,
    get_trainee_service,
)
from app.schemas.common import TraineeProfileOut
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
from app.services.auth_service import AuthService
from app.services.preference_service import PreferenceService
from app.services.profile_service import ProfileService
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
