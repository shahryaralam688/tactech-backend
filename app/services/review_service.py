"""Coach reviews & ratings.

Write eligibility: only a trainee currently linked (active roster) to that coach
may create / update / delete. Historical reviews stay visible after leave/remove.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.repositories.coach_profile import CoachProfileRepository
from app.repositories.reviews import (
    REPORT_HIDE_THRESHOLD,
    ReviewRepository,
    display_author_name,
    rating_avg_out,
)
from app.schemas.discovery import (
    CoachReviewCreateRequest,
    CoachReviewListPage,
    CoachReviewMineOut,
    CoachReviewOut,
    CoachReviewReportOut,
    CoachReviewReportRequest,
)

if TYPE_CHECKING:
    from app.api.deps import Principal

log = get_logger("tactech.reviews")

EligibilityReason = Literal["OK", "NOT_TRAINEE_ROLE", "NOT_ROSTERED", "IS_SELF"]


def is_currently_rostered_for_coach(
    db: Session, *, trainee_user_id: str, trainee_id: str | None, coach: models.CoachProfile
) -> bool:
    """True iff trainee has an active invite/roster link to this coach's trainer."""
    if not trainee_id:
        return False
    trainee = db.get(models.TraineeProfile, trainee_id)
    if trainee is None or trainee.user_id != trainee_user_id:
        return False
    if trainee.trainer_id == coach.trainer_id:
        return True
    # Durable active link row (covers pointer lag)
    active = db.scalars(
        select(models.TrainerTraineeLink)
        .where(
            models.TrainerTraineeLink.trainee_id == trainee.id,
            models.TrainerTraineeLink.trainer_id == coach.trainer_id,
            models.TrainerTraineeLink.status == "active",
        )
        .limit(1)
    ).first()
    return active is not None


def author_was_ever_linked_to_coach(
    db: Session, *, author_user_id: str, coach: models.CoachProfile
) -> bool:
    """Historical or current roster link — used for cleanup / eligible visibility."""
    trainee = db.scalars(
        select(models.TraineeProfile).where(models.TraineeProfile.user_id == author_user_id)
    ).first()
    if trainee is not None and trainee.trainer_id == coach.trainer_id:
        return True
    link = db.scalars(
        select(models.TrainerTraineeLink)
        .where(
            models.TrainerTraineeLink.trainee_user_id == author_user_id,
            models.TrainerTraineeLink.trainer_id == coach.trainer_id,
        )
        .limit(1)
    ).first()
    return link is not None


class ReviewService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.reviews = ReviewRepository(db)
        self.profiles = CoachProfileRepository(db)

    def create(
        self, principal: Principal, coach_profile_id: str, payload: CoachReviewCreateRequest
    ) -> CoachReviewOut:
        profile = self._require_eligible_writer(principal, coach_profile_id)
        stars, body = self._validate_payload(payload)

        existing = self.reviews.get_by_author_coach(
            author_user_id=principal.user_id,
            coach_profile_id=profile.id,
        )
        if existing is not None:
            raise ConflictError(
                "You already reviewed this coach. Update your review instead.",
                fields={"review": "exists"},
            )

        try:
            row = self.reviews.create(
                coach_profile_id=profile.id,
                trainer_id=profile.trainer_id,
                author_user_id=principal.user_id,
                author_trainee_id=principal.trainee_id,
                stars=stars,
                body=body,
            )
            self.reviews.recompute_aggregates(profile.id)
            self.db.commit()
            self.db.refresh(row)
        except IntegrityError:
            self.db.rollback()
            raise ConflictError(
                "You already reviewed this coach. Update your review instead.",
                fields={"review": "exists"},
            ) from None
        log.info(
            "coach_review_created",
            review_id=row.id,
            coach_profile_id=profile.id,
            author_user_id=principal.user_id,
            stars=stars,
        )
        return self._to_out(row, viewer_user_id=principal.user_id)

    def update_mine(
        self, principal: Principal, coach_profile_id: str, payload: CoachReviewCreateRequest
    ) -> CoachReviewOut:
        profile = self._require_eligible_writer(principal, coach_profile_id)
        row = self.reviews.get_by_author_coach(
            author_user_id=principal.user_id,
            coach_profile_id=profile.id,
        )
        if row is None:
            raise NotFoundError("Review not found.")
        stars, body = self._validate_payload(payload)
        row.stars = stars
        row.body = body
        self.reviews.save(row)
        self.reviews.recompute_aggregates(profile.id)
        self.db.commit()
        self.db.refresh(row)
        log.info("coach_review_updated", review_id=row.id, stars=stars)
        return self._to_out(row, viewer_user_id=principal.user_id)

    def delete_mine(self, principal: Principal, coach_profile_id: str) -> dict:
        profile = self._require_eligible_writer(principal, coach_profile_id)
        row = self.reviews.get_by_author_coach(
            author_user_id=principal.user_id,
            coach_profile_id=profile.id,
        )
        if row is None:
            raise NotFoundError("Review not found.")
        self.reviews.delete(row)
        self.reviews.recompute_aggregates(profile.id)
        self.db.commit()
        log.info("coach_review_deleted", coach_profile_id=profile.id, author_user_id=principal.user_id)
        return {"deleted": True}

    def get_mine(self, principal: Principal, coach_profile_id: str) -> CoachReviewMineOut:
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach not found.")

        can_review, reason = self._eligibility(principal, profile)
        row = None
        if principal.role == "trainee":
            row = self.reviews.get_by_author_coach(
                author_user_id=principal.user_id,
                coach_profile_id=profile.id,
            )
        review_out = (
            self._to_out(row, viewer_user_id=principal.user_id) if row is not None else None
        )
        return CoachReviewMineOut(
            review=review_out,
            can_review=can_review,
            reason=reason,
        )

    def list_reviews(
        self,
        principal: Principal,
        coach_profile_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> CoachReviewListPage:
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach not found.")
        is_owner = principal.user_id == profile.user_id
        if not profile.is_public and not is_owner:
            raise NotFoundError("Coach not found.")

        rows, next_cursor = self.reviews.list_for_coach(
            coach_profile_id=profile.id,
            viewer_user_id=principal.user_id,
            cursor=cursor,
            limit=limit,
        )
        items = [
            self._to_out(review, viewer_user_id=principal.user_id, author=user)
            for review, user in rows
        ]
        return CoachReviewListPage(
            rating_avg=rating_avg_out(profile.rating_avg),
            rating_count=int(profile.rating_count or 0),
            items=items,
            next_cursor=next_cursor,
        )

    def report(
        self, principal: Principal, review_id: str, payload: CoachReviewReportRequest
    ) -> CoachReviewReportOut:
        row = self.reviews.get(review_id)
        if row is None or row.is_hidden:
            raise NotFoundError("Review not found.")
        if row.author_user_id == principal.user_id:
            raise ForbiddenError("You cannot report your own review.")
        reason = (payload.reason or "").strip()
        if not reason:
            raise ValidationAppError("Reason is required.", fields={"reason": "required"})
        if len(reason) > 200:
            raise ValidationAppError(
                "Reason must be at most 200 characters.",
                fields={"reason": "too_long"},
            )

        created = self.reviews.try_add_report(
            review_id=row.id,
            reporter_user_id=principal.user_id,
            reason=reason,
        )
        if created:
            count = self.reviews.report_count(row.id)
            if count >= REPORT_HIDE_THRESHOLD and not row.is_hidden:
                row.is_hidden = True
                self.reviews.save(row)
                self.reviews.recompute_aggregates(row.coach_profile_id)
                log.info(
                    "coach_review_auto_hidden",
                    review_id=row.id,
                    report_count=count,
                    threshold=REPORT_HIDE_THRESHOLD,
                )
            self.db.commit()
        return CoachReviewReportOut(reported=True)

    def _eligibility(
        self, principal: Principal, profile: models.CoachProfile
    ) -> tuple[bool, EligibilityReason]:
        if principal.role != "trainee" or not principal.trainee_id:
            return False, "NOT_TRAINEE_ROLE"
        if principal.user_id == profile.user_id:
            return False, "IS_SELF"
        if is_currently_rostered_for_coach(
            self.db,
            trainee_user_id=principal.user_id,
            trainee_id=principal.trainee_id,
            coach=profile,
        ):
            return True, "OK"
        return False, "NOT_ROSTERED"

    def _require_eligible_writer(
        self, principal: Principal, coach_profile_id: str
    ) -> models.CoachProfile:
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach not found.")
        can_review, reason = self._eligibility(principal, profile)
        if reason == "NOT_TRAINEE_ROLE":
            raise ForbiddenError("Trainee access required.")
        if reason == "IS_SELF":
            raise ForbiddenError("You cannot review yourself.")
        if not can_review:
            raise ForbiddenError(
                "Only current trainees of this coach can leave a review.",
                code="NOT_ELIGIBLE",
            )
        return profile

    def _validate_payload(self, payload: CoachReviewCreateRequest) -> tuple[int, str | None]:
        stars = int(payload.stars)
        if stars < 1 or stars > 5:
            raise ValidationAppError(
                "Stars must be an integer from 1 to 5.",
                fields={"stars": "invalid"},
            )
        raw = (payload.body or "").strip()
        if len(raw) > 1000:
            raise ValidationAppError(
                "Review must be at most 1000 characters.",
                fields={"body": "too_long"},
            )
        body = raw or None
        return stars, body

    def _to_out(
        self,
        row: models.CoachReview,
        *,
        viewer_user_id: str,
        author: models.User | None = None,
    ) -> CoachReviewOut:
        if author is None:
            author = self.db.get(models.User, row.author_user_id)
        return CoachReviewOut(
            id=row.id,
            coach_profile_id=row.coach_profile_id,
            stars=row.stars,
            body=row.body,
            author_user_id=row.author_user_id,
            author_name=display_author_name(author.name if author else None),
            created_at=row.created_at,
            updated_at=row.updated_at,
            is_mine=row.author_user_id == viewer_user_id,
        )
