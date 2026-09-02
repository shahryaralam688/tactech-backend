from app.db import models
from app.schemas.common import (
    ExerciseOut,
    FoodKnowledgeOut,
    FormReportOut,
    MacroEstimateOut,
    MealOut,
    PlanAssignmentOut,
    TrainerFeedbackOut,
    TrainerProfileOut,
    TraineeProfileOut,
    UserPublic,
    WorkoutExerciseOut,
    WorkoutLogOut,
    WorkoutPlanOut,
    WorkoutSetLogOut,
)


def user_public(user: models.User) -> UserPublic:
    return UserPublic(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
    )


def trainer_out(trainer: models.TrainerProfile) -> TrainerProfileOut:
    return TrainerProfileOut.model_validate(trainer)


def trainee_out(trainee: models.TraineeProfile) -> TraineeProfileOut:
    return TraineeProfileOut.model_validate(trainee)


def exercise_out(exercise: models.Exercise) -> ExerciseOut:
    return ExerciseOut.model_validate(exercise)


def plan_out(plan: models.WorkoutPlan) -> WorkoutPlanOut:
    return WorkoutPlanOut(
        id=plan.id,
        trainer_id=plan.trainer_id,
        title=plan.title,
        focus=plan.focus,
        duration_minutes=plan.duration_minutes,
        level=plan.level,
        days_per_week=plan.days_per_week,
        exercises=[
            WorkoutExerciseOut(
                id=item.id,
                exercise_id=item.exercise_id,
                sets=item.sets,
                reps=item.reps,
                rest_seconds=item.rest_seconds,
                recommended_weight_kg=item.recommended_weight_kg,
            )
            for item in sorted(plan.exercises, key=lambda e: e.sort_order)
        ],
    )


def assignment_out(assignment: models.PlanAssignment) -> PlanAssignmentOut:
    return PlanAssignmentOut.model_validate(assignment)


def workout_log_out(log: models.WorkoutLog) -> WorkoutLogOut:
    return WorkoutLogOut(
        id=log.id,
        trainee_id=log.trainee_id,
        plan_id=log.plan_id,
        completed_at=log.completed_at,
        duration_minutes=log.duration_minutes,
        sets=[
            WorkoutSetLogOut(
                id=item.id,
                exercise_id=item.exercise_id,
                set_number=item.set_number,
                reps=item.reps,
                weight_kg=item.weight_kg,
            )
            for item in log.sets
        ],
    )


def meal_out(meal: models.Meal) -> MealOut:
    return MealOut(
        id=meal.id,
        trainee_id=meal.trainee_id,
        name=meal.name,
        eaten_at=meal.eaten_at,
        portion_grams=meal.portion_grams,
        macros=MacroEstimateOut(
            calories=meal.calories,
            protein=meal.protein,
            carbs=meal.carbs,
            fat=meal.fat,
        ),
        source=meal.source,
        is_estimate=meal.is_estimate,
    )


def feedback_out(item: models.TrainerFeedback) -> TrainerFeedbackOut:
    return TrainerFeedbackOut.model_validate(item)


def form_report_out(report: models.FormReport) -> FormReportOut:
    return FormReportOut.model_validate(report)


def food_out(food: models.FoodKnowledge) -> FoodKnowledgeOut:
    return FoodKnowledgeOut(
        name=food.name,
        keywords=list(food.keywords),
        per100g=MacroEstimateOut(
            calories=food.calories,
            protein=food.protein,
            carbs=food.carbs,
            fat=food.fat,
        ),
    )
