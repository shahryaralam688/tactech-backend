from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Principal, get_trainee_service, require_trainee
from app.schemas.common import (
    FoodKnowledgeOut,
    FormReportOut,
    MealOut,
    TrainerFeedbackOut,
    TraineeProfileOut,
    WorkoutLogOut,
    WorkoutPlanOut,
)
from app.schemas.requests import (
    CreateFormReportRequest,
    CreateMealRequest,
    CreateWorkoutLogRequest,
    LinkTrainerRequest,
)
from app.schemas.responses import DailyMacrosResponse, TrainerPublic
from app.services.trainee_service import TraineeService

router = APIRouter(prefix="/trainee", tags=["trainee"])


@router.post("/link", response_model=TraineeProfileOut)
def link_trainer(
    payload: LinkTrainerRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> TraineeProfileOut:
    return service.link_trainer(principal.trainee_id, payload.invite_code)  # type: ignore[arg-type]


@router.get("/trainer", response_model=TrainerPublic | None)
def my_trainer(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> TrainerPublic | None:
    return service.my_trainer(principal.trainee_id)  # type: ignore[arg-type]


@router.get("/assigned-plan", response_model=WorkoutPlanOut | None)
def assigned_plan(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> WorkoutPlanOut | None:
    return service.assigned_plan(principal.trainee_id)  # type: ignore[arg-type]


@router.get("/logs", response_model=list[WorkoutLogOut])
def list_logs(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> list[WorkoutLogOut]:
    return service.list_logs(principal.trainee_id)  # type: ignore[arg-type]


@router.post("/logs", response_model=WorkoutLogOut, status_code=status.HTTP_201_CREATED)
def save_log(
    payload: CreateWorkoutLogRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> WorkoutLogOut:
    return service.save_log(principal.trainee_id, payload)  # type: ignore[arg-type]


@router.get("/meals", response_model=list[MealOut])
def list_meals(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
    on: date | None = Query(default=None),
) -> list[MealOut]:
    return service.list_meals(principal.trainee_id, on)  # type: ignore[arg-type]


@router.post("/meals", response_model=MealOut, status_code=status.HTTP_201_CREATED)
def save_meal(
    payload: CreateMealRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> MealOut:
    return service.save_meal(principal.trainee_id, payload)  # type: ignore[arg-type]


@router.get("/macros", response_model=DailyMacrosResponse)
def daily_macros(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
    on: date = Query(...),
) -> DailyMacrosResponse:
    return service.daily_macros(principal.trainee_id, on)  # type: ignore[arg-type]


@router.get("/feedback", response_model=list[TrainerFeedbackOut])
def list_feedback(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> list[TrainerFeedbackOut]:
    return service.list_feedback(principal.trainee_id)  # type: ignore[arg-type]


@router.get("/form-reports", response_model=list[FormReportOut])
def list_form_reports(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> list[FormReportOut]:
    return service.list_form_reports(principal.trainee_id)  # type: ignore[arg-type]


@router.post("/form-reports", response_model=FormReportOut, status_code=status.HTTP_201_CREATED)
def save_form_report(
    payload: CreateFormReportRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> FormReportOut:
    return service.save_form_report(principal.trainee_id, payload)  # type: ignore[arg-type]


@router.get("/food/lookup", response_model=FoodKnowledgeOut | None)
def lookup_food(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
    q: str = Query(..., min_length=1),
) -> FoodKnowledgeOut | None:
    _ = principal
    return service.lookup_food(q)
