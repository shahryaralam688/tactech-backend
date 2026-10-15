from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, status

from app.api.deps import (
    Principal,
    get_assessment_service,
    get_join_request_service,
    get_trainee_service,
    require_trainee,
)
from app.schemas.assessment import AssessmentProgramOut, AssessmentRequest
from app.services.assessment_service import AssessmentService
from app.schemas.common import (
    FoodKnowledgeOut,
    FormReportOut,
    MealOut,
    TrainerFeedbackOut,
    WorkoutLogOut,
    WorkoutPlanOut,
)
from app.schemas.join_requests import (
    JoinRequestCreate,
    JoinRequestOut,
    JoinRequestStatusOut,
    TraineeJoinStateOut,
)
from app.schemas.requests import (
    CreateFormReportRequest,
    CreateMealRequest,
    CreateWorkoutLogRequest,
    LinkTrainerRequest,
    UpdateMealRequest,
    UpdatePlanRequest,
    UpdateWorkoutLogRequest,
)
from app.schemas.responses import DailyMacrosResponse, TrainerPublic
from app.schemas.roster import UnlinkOut
from app.services.join_request_service import JoinRequestService
from app.services.trainee_service import TraineeService

router = APIRouter(prefix="/trainee", tags=["trainee"])


@router.post("/assessment", response_model=AssessmentProgramOut, status_code=status.HTTP_201_CREATED)
def submit_assessment(
    payload: AssessmentRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[AssessmentService, Depends(get_assessment_service)],
) -> AssessmentProgramOut:
    return service.submit(principal.trainee_id, payload)  # type: ignore[arg-type]


@router.get("/assessment", response_model=AssessmentProgramOut | None)
def latest_assessment(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[AssessmentService, Depends(get_assessment_service)],
) -> AssessmentProgramOut | None:
    return service.latest_for_trainee(principal.trainee_id)  # type: ignore[arg-type]


@router.post(
    "/join-requests",
    response_model=JoinRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def create_join_request(
    payload: JoinRequestCreate,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[JoinRequestService, Depends(get_join_request_service)],
) -> JoinRequestOut:
    """Create a pending join request (does not activate roster until trainer Accept)."""
    return service.create(
        trainee_id=principal.trainee_id,  # type: ignore[arg-type]
        trainee_user_id=principal.user_id,
        payload=payload,
    )


@router.get("/join-requests/mine", response_model=TraineeJoinStateOut)
def my_join_state(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[JoinRequestService, Depends(get_join_request_service)],
) -> TraineeJoinStateOut:
    return service.mine(
        trainee_id=principal.trainee_id,  # type: ignore[arg-type]
        trainee_user_id=principal.user_id,
    )


@router.post("/join-requests/{request_id}/cancel", response_model=JoinRequestStatusOut)
def cancel_join_request(
    request_id: str,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[JoinRequestService, Depends(get_join_request_service)],
) -> JoinRequestStatusOut:
    return service.cancel(trainee_user_id=principal.user_id, request_id=request_id)


@router.post(
    "/link",
    response_model=JoinRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Alias: create pending join request (no longer auto-links)",
)
def link_trainer(
    payload: LinkTrainerRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[JoinRequestService, Depends(get_join_request_service)],
) -> JoinRequestOut:
    """Breaking: formerly instant-linked. Now creates a pending join request (Option 1)."""
    return service.create(
        trainee_id=principal.trainee_id,  # type: ignore[arg-type]
        trainee_user_id=principal.user_id,
        payload=JoinRequestCreate(invite_code=payload.invite_code, message=None),
    )


@router.post("/unlink", response_model=UnlinkOut)
def unlink_trainer(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
    _body: dict[str, Any] | None = Body(default=None),
) -> UnlinkOut:
    """Trainee leaves trainer roster — clears plan assignment; chat kept.

    Accepts empty body, `{}`, or no body (iOS Leave sends empty JSON).
    """
    return service.unlink_trainer(principal.trainee_id)  # type: ignore[arg-type]


@router.get("/trainer", response_model=TrainerPublic | None)
def my_trainer(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> TrainerPublic | None:
    """Linked trainer, or null when unlinked (200)."""
    return service.my_trainer(principal.trainee_id)  # type: ignore[arg-type]


@router.get("/assigned-plan", response_model=WorkoutPlanOut | None)
def assigned_plan(
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> WorkoutPlanOut | None:
    return service.assigned_plan(principal.trainee_id)  # type: ignore[arg-type]


@router.patch("/ai-plans/{plan_id}", response_model=WorkoutPlanOut)
def update_ai_plan(
    plan_id: str,
    payload: UpdatePlanRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> WorkoutPlanOut:
    """Edit AI solo plan only (`source=ai`). Trainer plans → 403 PLAN_LOCKED."""
    return service.update_ai_plan(principal.trainee_id, plan_id, payload)  # type: ignore[arg-type]


@router.delete("/ai-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_plan(
    plan_id: str,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> None:
    """Delete AI solo plan only (`source=ai`). Clears assignment."""
    service.delete_ai_plan(principal.trainee_id, plan_id)  # type: ignore[arg-type]


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


@router.patch("/logs/{log_id}", response_model=WorkoutLogOut)
def update_log(
    log_id: str,
    payload: UpdateWorkoutLogRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> WorkoutLogOut:
    return service.update_log(principal.trainee_id, log_id, payload)  # type: ignore[arg-type]


@router.delete("/logs/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log(
    log_id: str,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> None:
    service.delete_log(principal.trainee_id, log_id)  # type: ignore[arg-type]


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


@router.patch("/meals/{meal_id}", response_model=MealOut)
def update_meal(
    meal_id: str,
    payload: UpdateMealRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> MealOut:
    return service.update_meal(principal.trainee_id, meal_id, payload)  # type: ignore[arg-type]


@router.delete("/meals/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meal(
    meal_id: str,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[TraineeService, Depends(get_trainee_service)],
) -> None:
    service.delete_meal(principal.trainee_id, meal_id)  # type: ignore[arg-type]


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
