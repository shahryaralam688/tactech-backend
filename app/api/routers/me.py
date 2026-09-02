from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Principal, get_auth_service, get_principal, get_trainer_service, get_trainee_service
from app.schemas.common import TraineeProfileOut
from app.schemas.requests import UpdateTraineeProfileRequest, UpdateTrainerProfileRequest
from app.schemas.responses import MeResponse, TrainerPublic
from app.services.auth_service import AuthService
from app.services.trainee_service import TraineeService
from app.services.trainer_service import TrainerService

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
def me(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MeResponse:
    return service.me(principal.user_id)


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
