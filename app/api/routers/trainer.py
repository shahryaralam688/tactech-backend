from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Principal, get_trainer_service, require_trainer
from app.schemas.common import (
    FormReportOut,
    MacroEstimateOut,
    MealOut,
    TrainerFeedbackOut,
    WorkoutLogOut,
    WorkoutPlanOut,
)
from app.schemas.requests import AssignPlanRequest, CreateFeedbackRequest, CreatePlanRequest
from app.schemas.responses import AssignmentResponse, TraineeRosterItem
from app.services.trainer_service import TrainerService

router = APIRouter(prefix="/trainer", tags=["trainer"])


@router.get("/trainees", response_model=list[TraineeRosterItem])
def list_trainees(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> list[TraineeRosterItem]:
    return service.list_trainees(principal.trainer_id)  # type: ignore[arg-type]


@router.get("/trainees/{trainee_id}", response_model=TraineeRosterItem)
def get_trainee(
    trainee_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> TraineeRosterItem:
    return service.get_trainee(principal.trainer_id, trainee_id)  # type: ignore[arg-type]


@router.get("/trainees/{trainee_id}/meals", response_model=list[MealOut])
def trainee_meals(
    trainee_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
    on: date | None = Query(default=None),
) -> list[MealOut]:
    return service.trainee_meals(principal.trainer_id, trainee_id, on)  # type: ignore[arg-type]


@router.get("/trainees/{trainee_id}/macros", response_model=MacroEstimateOut)
def trainee_macros(
    trainee_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
    on: date = Query(...),
) -> MacroEstimateOut:
    return service.trainee_macros(principal.trainer_id, trainee_id, on)  # type: ignore[arg-type]


@router.get("/trainees/{trainee_id}/logs", response_model=list[WorkoutLogOut])
def trainee_logs(
    trainee_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> list[WorkoutLogOut]:
    return service.trainee_logs(principal.trainer_id, trainee_id)  # type: ignore[arg-type]


@router.get("/trainees/{trainee_id}/form-reports", response_model=list[FormReportOut])
def trainee_form_reports(
    trainee_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> list[FormReportOut]:
    return service.trainee_form_reports(principal.trainer_id, trainee_id)  # type: ignore[arg-type]


@router.get("/trainees/{trainee_id}/feedback", response_model=list[TrainerFeedbackOut])
def trainee_feedback(
    trainee_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> list[TrainerFeedbackOut]:
    return service.trainee_feedback(principal.trainer_id, trainee_id)  # type: ignore[arg-type]


@router.get("/plans", response_model=list[WorkoutPlanOut])
def list_plans(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> list[WorkoutPlanOut]:
    return service.list_plans(principal.trainer_id)  # type: ignore[arg-type]


@router.post("/plans", response_model=WorkoutPlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: CreatePlanRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> WorkoutPlanOut:
    return service.create_plan(principal.trainer_id, payload)  # type: ignore[arg-type]


@router.get("/plans/{plan_id}", response_model=WorkoutPlanOut)
def get_plan(
    plan_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> WorkoutPlanOut:
    return service.get_plan(principal.trainer_id, plan_id)  # type: ignore[arg-type]


@router.post("/assignments", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
def assign_plan(
    payload: AssignPlanRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> AssignmentResponse:
    return service.assign_plan(principal.trainer_id, payload)  # type: ignore[arg-type]


@router.post("/feedback", response_model=TrainerFeedbackOut, status_code=status.HTTP_201_CREATED)
def save_feedback(
    payload: CreateFeedbackRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> TrainerFeedbackOut:
    return service.save_feedback(principal.trainer_id, payload)  # type: ignore[arg-type]
