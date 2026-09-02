from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import models


class TraineeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, trainee_id: str) -> models.TraineeProfile | None:
        return self.db.get(models.TraineeProfile, trainee_id)

    def get_by_user_id(self, user_id: str) -> models.TraineeProfile | None:
        stmt = select(models.TraineeProfile).where(models.TraineeProfile.user_id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_with_user(self, trainee_id: str) -> models.TraineeProfile | None:
        stmt = (
            select(models.TraineeProfile)
            .options(joinedload(models.TraineeProfile.user))
            .where(models.TraineeProfile.id == trainee_id)
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def list_for_trainer(self, trainer_id: str) -> list[models.TraineeProfile]:
        stmt = (
            select(models.TraineeProfile)
            .options(joinedload(models.TraineeProfile.user))
            .where(models.TraineeProfile.trainer_id == trainer_id)
            .order_by(models.TraineeProfile.id)
        )
        return list(self.db.execute(stmt).unique().scalars().all())

    def add(self, trainee: models.TraineeProfile) -> models.TraineeProfile:
        self.db.add(trainee)
        self.db.flush()
        return trainee
