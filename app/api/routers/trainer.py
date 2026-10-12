from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    Principal,
    get_assessment_service,
    get_template_service,
    get_trainer_service,
    require_trainer,
)
from app.core.exceptions import ValidationAppError
from app.schemas.assessment import AssessmentProgramOut, TrainerAssessmentOut
from app.services.assessment_service import AssessmentService
from app.schemas.common import (
    FormReportOut,
    MacroEstimateOut,
    MealOut,
    TrainerFeedbackOut,
    WorkoutLogOut,
    WorkoutPlanOut,
)
from app.schemas.requests import (
    AssignPlanRequest,
    CreateFeedbackRequest,
    CreatePlanRequest,
    TrainerAssessmentRequest,
    UpdatePlanRequest,
)
from app.schemas.responses import AssignmentResponse, TraineeAnalyticsOut, TraineeRosterItem
from app.schemas.templates import ExerciseTemplateIn, ExerciseTemplateOut, UpdateExerciseTemplateRequest
from app.services.template_service import TemplateService
from app.services.trainer_service import TrainerService

router = APIRouter(prefix="/trainer", tags=["trainer"])


@router.get("/trainees", response_model=list[TraineeRosterItem])
def list_trainees(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> list[TraineeRosterItem]:
    return service.list_trainees(principal.trainer_id)  # type: ignore[arg-type]


@router.get("/trainees/{trainee_id}/assessment", response_model=AssessmentProgramOut | None)
def trainee_assessment(
    trainee_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[AssessmentService, Depends(get_assessment_service)],
) -> AssessmentProgramOut | None:
    return service.latest_for_trainer(principal.trainer_id, trainee_id)  # type: ignore[arg-type]


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


@router.get("/trainees/{trainee_id}/analytics", response_model=TraineeAnalyticsOut)
def trainee_analytics(
    trainee_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
    period_days: int = Query(default=30, ge=1, le=90),
) -> TraineeAnalyticsOut:
    """Workout history rollup for trainer Analytics / History screens."""
    return service.trainee_analytics(principal.trainer_id, trainee_id, period_days=period_days)  # type: ignore[arg-type]


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


@router.patch("/plans/{plan_id}", response_model=WorkoutPlanOut)
def update_plan(
    plan_id: str,
    payload: UpdatePlanRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> WorkoutPlanOut:
    return service.update_plan(principal.trainer_id, plan_id, payload)  # type: ignore[arg-type]


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(
    plan_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> None:
    service.delete_plan(principal.trainer_id, plan_id)  # type: ignore[arg-type]


@router.get("/exercise-templates", response_model=list[ExerciseTemplateOut])
def list_exercise_templates(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TemplateService, Depends(get_template_service)],
    exercise_id: str | None = Query(default=None),
) -> list[ExerciseTemplateOut]:
    return service.list_templates(principal.trainer_id, exercise_id)  # type: ignore[arg-type]


@router.post("/exercise-templates", response_model=ExerciseTemplateOut, status_code=status.HTTP_201_CREATED)
def create_exercise_template(
    payload: ExerciseTemplateIn,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TemplateService, Depends(get_template_service)],
) -> ExerciseTemplateOut:
    return service.create(principal.trainer_id, payload)  # type: ignore[arg-type]


@router.patch("/exercise-templates/{template_id}", response_model=ExerciseTemplateOut)
def update_exercise_template(
    template_id: str,
    payload: UpdateExerciseTemplateRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TemplateService, Depends(get_template_service)],
) -> ExerciseTemplateOut:
    return service.update(principal.trainer_id, template_id, payload)  # type: ignore[arg-type]


@router.delete("/exercise-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exercise_template(
    template_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TemplateService, Depends(get_template_service)],
) -> None:
    service.delete(principal.trainer_id, template_id)  # type: ignore[arg-type]


@router.post("/assessment", response_model=TrainerAssessmentOut, status_code=status.HTTP_201_CREATED)
def trainer_assessment(
    payload: TrainerAssessmentRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> TrainerAssessmentOut:
    return service.save_trainer_assessment(principal.trainer_id, payload)  # type: ignore[arg-type]


@router.post("/assignments", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
def assign_plan(
    payload: AssignPlanRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> AssignmentResponse:
    return service.assign_plan(principal.trainer_id, payload)  # type: ignore[arg-type]


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_by_id(
    assignment_id: str,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> None:
    service.unassign_plan(principal.trainer_id, assignment_id=assignment_id)  # type: ignore[arg-type]


@router.delete("/assignments", status_code=status.HTTP_204_NO_CONTENT)
def unassign_by_query(
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
    plan_id: str | None = Query(default=None, alias="planId"),
    trainee_id: str | None = Query(default=None, alias="traineeId"),
) -> None:
    # Also accept snake_case for clients that send it.
    if not plan_id or not trainee_id:
        raise ValidationAppError("Provide planId and traineeId.")
    service.unassign_plan(principal.trainer_id, plan_id=plan_id, trainee_id=trainee_id)  # type: ignore[arg-type]


@router.post("/feedback", response_model=TrainerFeedbackOut, status_code=status.HTTP_201_CREATED)
def save_feedback(
    payload: CreateFeedbackRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[TrainerService, Depends(get_trainer_service)],
) -> TrainerFeedbackOut:
    return service.save_feedback(principal.trainer_id, payload)  # type: ignore[arg-type]
