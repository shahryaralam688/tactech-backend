"""Admin exercise catalog + Form Studio 3D — protected by X-Admin-Key."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_exercise_admin_service, require_admin_key
from app.schemas.common import ExerciseOut
from app.schemas.form3d_admin import (
    ExerciseCreateRequest,
    Form3dUpdateRequest,
    Form3dUploadOut,
)
from app.services.exercise_admin_service import ExerciseAdminService

router = APIRouter(prefix="/admin", tags=["admin-exercises"])


@router.put("/exercises/{exercise_id}/form3d", response_model=ExerciseOut)
def put_exercise_form3d(
    exercise_id: str,
    payload: Form3dUpdateRequest,
    _: Annotated[str, Depends(require_admin_key)],
    service: Annotated[ExerciseAdminService, Depends(get_exercise_admin_service)],
) -> ExerciseOut:
    return service.update_form3d(exercise_id, payload)


@router.post("/exercises", response_model=ExerciseOut, status_code=201)
def create_exercise(
    payload: ExerciseCreateRequest,
    _: Annotated[str, Depends(require_admin_key)],
    service: Annotated[ExerciseAdminService, Depends(get_exercise_admin_service)],
) -> ExerciseOut:
    return service.create_exercise(payload)


@router.post("/form3d/uploads", response_model=Form3dUploadOut)
async def upload_form3d_asset(
    _: Annotated[str, Depends(require_admin_key)],
    service: Annotated[ExerciseAdminService, Depends(get_exercise_admin_service)],
    file: UploadFile = File(...),
) -> Form3dUploadOut:
    data = await file.read()
    return service.upload_form3d(
        filename=file.filename or "clip.fbx",
        data=data,
        content_type=file.content_type,
    )
