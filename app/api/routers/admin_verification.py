"""Admin coach verification review — protected by X-Admin-Key."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_verification_service, require_admin_key
from app.schemas.verification import (
    AdminActionOut,
    AdminApplicationPage,
    AdminRejectRequest,
)
from app.services.verification_service import VerificationService

router = APIRouter(prefix="/admin/coach-verification", tags=["admin-verification"])


@router.get("/applications", response_model=AdminApplicationPage)
def list_applications(
    _: Annotated[str, Depends(require_admin_key)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
    status: Annotated[str | None, Query()] = "submitted",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminApplicationPage:
    return service.admin_list(status=status, limit=limit)


@router.post("/applications/{application_id}/approve", response_model=AdminActionOut)
def approve_application(
    application_id: str,
    reviewer: Annotated[str, Depends(require_admin_key)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> AdminActionOut:
    return service.admin_approve(application_id, reviewer_label=reviewer)


@router.post("/applications/{application_id}/reject", response_model=AdminActionOut)
def reject_application(
    application_id: str,
    payload: AdminRejectRequest,
    reviewer: Annotated[str, Depends(require_admin_key)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> AdminActionOut:
    return service.admin_reject(application_id, payload, reviewer_label=reviewer)


@router.post("/revoke/{coach_profile_id}", response_model=AdminActionOut)
def revoke_verification(
    coach_profile_id: str,
    reviewer: Annotated[str, Depends(require_admin_key)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> AdminActionOut:
    return service.admin_revoke(coach_profile_id, reviewer_label=reviewer)
