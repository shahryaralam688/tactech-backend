"""Helpers for assessment / onboarding completion gates (iOS source of truth)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def mark_assessment_completed(db: Session, user: models.User | None) -> None:
    if user is None:
        return
    user.assessment_completed = True
    user.onboarding_completed = True


def maybe_mark_onboarding_completed(
    db: Session,
    user: models.User,
    *,
    trainer: models.TrainerProfile | None = None,
    trainee: models.TraineeProfile | None = None,
) -> None:
    """Flip onboarding when Personal Info essentials are present.

    Essentials: name + gender + location.
    Trainee height/weight are optional for this gate (Profile Setup / Personal Info).
    """
    if user.onboarding_completed:
        return
    if not (user.name or "").strip():
        return
    if not (user.gender or "").strip():
        return
    if not (user.location or "").strip():
        return
    user.onboarding_completed = True


def heal_completion_flags(db: Session, user: models.User) -> None:
    """Lazy heal for users assessed before flags existed."""
    if not user.assessment_completed:
        if user.role == "trainee":
            trainee = db.scalars(
                select(models.TraineeProfile).where(models.TraineeProfile.user_id == user.id)
            ).first()
            if trainee is not None:
                has = db.scalars(
                    select(models.FitnessAssessment.id)
                    .where(models.FitnessAssessment.trainee_id == trainee.id)
                    .limit(1)
                ).first()
                if has:
                    user.assessment_completed = True
                    user.onboarding_completed = True
                    return
        elif user.role == "trainer":
            trainer = db.scalars(
                select(models.TrainerProfile).where(models.TrainerProfile.user_id == user.id)
            ).first()
            if trainer is not None:
                has = db.scalars(
                    select(models.TrainerAssessment.id)
                    .where(models.TrainerAssessment.trainer_id == trainer.id)
                    .limit(1)
                ).first()
                if has:
                    user.assessment_completed = True
                    user.onboarding_completed = True
                    return

    if not user.onboarding_completed:
        trainer = (
            db.scalars(select(models.TrainerProfile).where(models.TrainerProfile.user_id == user.id)).first()
            if user.role == "trainer"
            else None
        )
        trainee = (
            db.scalars(select(models.TraineeProfile).where(models.TraineeProfile.user_id == user.id)).first()
            if user.role == "trainee"
            else None
        )
        maybe_mark_onboarding_completed(db, user, trainer=trainer, trainee=trainee)
