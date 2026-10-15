from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    Principal,
    get_analytics_service,
    get_discovery_service,
    get_follow_service,
    get_package_service,
    get_principal,
    get_review_service,
    require_trainee,
)
from app.schemas.analytics import ImpressionsOut, ImpressionsRequest
from app.schemas.discovery import (
    CoachContactOut,
    CoachContactRequest,
    CoachDetailOut,
    CoachListPage,
    CoachReviewCreateRequest,
    CoachReviewListPage,
    CoachReviewMineOut,
    CoachReviewOut,
    CoachReviewReportOut,
    CoachReviewReportRequest,
)
from app.schemas.follows import CoachFollowOut, FollowCreateRequest, FollowStateOut
from app.schemas.packages import (
    CoachPackageOut,
    CoachPackagePage,
    PackageInquireOut,
    PackageInquireRequest,
)
from app.services.analytics_service import AnalyticsService
from app.services.discovery_service import DiscoveryService
from app.services.follow_service import FollowService
from app.services.package_service import PackageService
from app.services.review_service import ReviewService

router = APIRouter(prefix="/coaches", tags=["coaches"])


@router.get("", response_model=CoachListPage)
def list_coaches(
    _: Annotated[Principal, Depends(get_principal)],
    service: Annotated[DiscoveryService, Depends(get_discovery_service)],
    q: Annotated[str | None, Query()] = None,
    city: Annotated[str | None, Query()] = None,
    specialty: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CoachListPage:
    return service.list_coaches(q=q, city=city, specialty=specialty, cursor=cursor, limit=limit)


@router.post("/events/impressions", response_model=ImpressionsOut)
def record_impressions(
    payload: ImpressionsRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> ImpressionsOut:
    """Discovery list impressions — max 1 per viewer↔coach per 15 minutes."""
    return service.record_impressions(principal, payload)


@router.get("/{coach_profile_id}/packages", response_model=CoachPackagePage)
def list_coach_packages(
    coach_profile_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PackageService, Depends(get_package_service)],
) -> CoachPackagePage:
    return service.list_public(principal, coach_profile_id)


@router.get("/{coach_profile_id}/packages/{package_id}", response_model=CoachPackageOut)
def get_coach_package(
    coach_profile_id: str,
    package_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[PackageService, Depends(get_package_service)],
) -> CoachPackageOut:
    return service.get_public(principal, coach_profile_id, package_id)


@router.post(
    "/{coach_profile_id}/packages/{package_id}/inquire",
    response_model=PackageInquireOut,
)
def inquire_coach_package(
    coach_profile_id: str,
    package_id: str,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[PackageService, Depends(get_package_service)],
    body: PackageInquireRequest | None = None,
) -> PackageInquireOut:
    return service.inquire(principal, coach_profile_id, package_id, body)


@router.post("/reviews/{review_id}/report", response_model=CoachReviewReportOut)
def report_review(
    review_id: str,
    payload: CoachReviewReportRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> CoachReviewReportOut:
    return service.report(principal, review_id, payload)


@router.get("/{coach_profile_id}/reviews/me", response_model=CoachReviewMineOut)
def get_my_review(
    coach_profile_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> CoachReviewMineOut:
    """Own review (if any) + canReview / reason for Write/Edit affordances."""
    return service.get_mine(principal, coach_profile_id)


@router.put("/{coach_profile_id}/reviews/me", response_model=CoachReviewOut)
def update_my_review(
    coach_profile_id: str,
    payload: CoachReviewCreateRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> CoachReviewOut:
    return service.update_mine(principal, coach_profile_id, payload)


@router.delete("/{coach_profile_id}/reviews/me")
def delete_my_review(
    coach_profile_id: str,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> dict:
    return service.delete_mine(principal, coach_profile_id)


@router.get("/{coach_profile_id}/reviews", response_model=CoachReviewListPage)
def list_reviews(
    coach_profile_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ReviewService, Depends(get_review_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CoachReviewListPage:
    return service.list_reviews(principal, coach_profile_id, cursor=cursor, limit=limit)


@router.post(
    "/{coach_profile_id}/reviews",
    response_model=CoachReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    coach_profile_id: str,
    payload: CoachReviewCreateRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> CoachReviewOut:
    return service.create(principal, coach_profile_id, payload)


@router.get("/{coach_profile_id}/follow", response_model=FollowStateOut)
def get_follow_state(
    coach_profile_id: str,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[FollowService, Depends(get_follow_service)],
) -> FollowStateOut:
    return service.get_follow_state(principal, coach_profile_id)


@router.post("/{coach_profile_id}/follow", response_model=CoachFollowOut)
def create_follow(
    coach_profile_id: str,
    response: Response,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[FollowService, Depends(get_follow_service)],
    body: FollowCreateRequest | None = None,
) -> CoachFollowOut:
    out, code = service.create_follow(principal, coach_profile_id, body)
    response.status_code = code
    return out


@router.post("/{coach_profile_id}/follow/cancel", response_model=CoachFollowOut)
def cancel_follow(
    coach_profile_id: str,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[FollowService, Depends(get_follow_service)],
) -> CoachFollowOut:
    return service.cancel_pending(principal, coach_profile_id)


@router.get("/{coach_profile_id}", response_model=CoachDetailOut)
def get_coach(
    coach_profile_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> CoachDetailOut:
    return service.get_coach(principal, coach_profile_id)


@router.post("/{coach_profile_id}/contact", response_model=CoachContactOut)
def contact_coach(
    coach_profile_id: str,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[DiscoveryService, Depends(get_discovery_service)],
    body: CoachContactRequest | None = None,
) -> CoachContactOut:
    message = body.message if body else None
    return service.contact_coach(principal, coach_profile_id, message=message)
