"""Coach reviews & ratings (Phase 5).

Eligibility (Option A): trainee may review if coach isPublic OR invite-linked
to that trainer. No chat-thread requirement. No payment required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


class ReviewService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.reviews = ReviewRepository(db)
        self.profiles = CoachProfileRepository(db)

    def create(
        self, principal: Principal, coach_profile_id: str, payload: CoachReviewCreateRequest
    ) -> CoachReviewOut:
        self._require_trainee(principal)
        profile = self._reviewable_profile(principal, coach_profile_id)
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
        self._require_trainee(principal)
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach not found.")
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
        self._require_trainee(principal)
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach not found.")
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
        self._require_trainee(principal)
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach not found.")
        row = self.reviews.get_by_author_coach(
            author_user_id=principal.user_id,
            coach_profile_id=profile.id,
        )
        if row is None:
            return CoachReviewMineOut(review=None)
        return CoachReviewMineOut(review=self._to_out(row, viewer_user_id=principal.user_id))

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
        # Same visibility as detail: public or owner
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
            # Hide existence of hidden reviews to reporters
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

    def _require_trainee(self, principal: Principal) -> None:
        if principal.role != "trainee" or not principal.trainee_id:
            raise ForbiddenError("Trainee access required.")

    def _reviewable_profile(
        self, principal: Principal, coach_profile_id: str
    ) -> models.CoachProfile:
        profile = self.profiles.get_by_id(coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach not found.")
        if principal.user_id == profile.user_id:
            raise ForbiddenError("You cannot review yourself.")
        # Option A: public OR invite-linked
        if profile.is_public:
            return profile
        trainee = self.db.get(models.TraineeProfile, principal.trainee_id)
        if trainee is not None and trainee.trainer_id == profile.trainer_id:
            return profile
        raise NotFoundError("Coach not found.")

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
