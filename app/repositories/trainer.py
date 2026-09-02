from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db import models


class TrainerRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, trainer_id: str) -> models.TrainerProfile | None:
        return self.db.get(models.TrainerProfile, trainer_id)

    def get_by_user_id(self, user_id: str) -> models.TrainerProfile | None:
        stmt = select(models.TrainerProfile).where(models.TrainerProfile.user_id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_invite_code(self, invite_code: str) -> models.TrainerProfile | None:
        stmt = select(models.TrainerProfile).where(
            func.lower(models.TrainerProfile.invite_code) == invite_code.lower()
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_with_user(self, trainer_id: str) -> models.TrainerProfile | None:
        stmt = (
            select(models.TrainerProfile)
            .options(joinedload(models.TrainerProfile.user))
            .where(models.TrainerProfile.id == trainer_id)
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def add(self, trainer: models.TrainerProfile) -> models.TrainerProfile:
        self.db.add(trainer)
        self.db.flush()
        return trainer

    def invite_code_exists(self, invite_code: str) -> bool:
        stmt = select(models.TrainerProfile.id).where(
            func.lower(models.TrainerProfile.invite_code) == invite_code.lower()
        )
        return self.db.execute(stmt).scalar_one_or_none() is not None
