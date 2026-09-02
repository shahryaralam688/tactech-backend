from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.repositories.exercise import ExerciseRepository
from app.repositories.food import FoodRepository
from app.schemas.common import ExerciseOut, FoodKnowledgeOut
from app.schemas.mappers import exercise_out, food_out

router = APIRouter(tags=["catalog"])


@router.get("/exercises", response_model=list[ExerciseOut])
def list_exercises(
    _: Annotated[Principal, Depends(get_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ExerciseOut]:
    return [exercise_out(item) for item in ExerciseRepository(db).list_all()]


@router.get("/exercises/{exercise_id}", response_model=ExerciseOut)
def get_exercise(
    exercise_id: str,
    _: Annotated[Principal, Depends(get_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> ExerciseOut:
    exercise = ExerciseRepository(db).get(exercise_id)
    if exercise is None:
        raise NotFoundError("Exercise not found.")
    return exercise_out(exercise)


@router.get("/food/lookup", response_model=FoodKnowledgeOut | None)
def lookup_food(
    _: Annotated[Principal, Depends(get_principal)],
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(..., min_length=1),
) -> FoodKnowledgeOut | None:
    food = FoodRepository(db).lookup(q)
    return food_out(food) if food else None
