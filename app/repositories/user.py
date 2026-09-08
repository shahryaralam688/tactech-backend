from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import models


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: str) -> models.User | None:
        return self.db.get(models.User, user_id)

    def get_active(self, user_id: str) -> models.User | None:
        user = self.get(user_id)
        if user is None or user.deleted_at is not None:
            return None
        return user

    def get_with_roles(self, user_id: str) -> models.User | None:
        stmt = (
            select(models.User)
            .options(joinedload(models.User.trainer), joinedload(models.User.trainee))
            .where(models.User.id == user_id)
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def get_by_email(self, email: str, *, include_deleted: bool = False) -> models.User | None:
        stmt = select(models.User).where(models.User.email == email)
        if not include_deleted:
            stmt = stmt.where(models.User.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def add(self, user: models.User) -> models.User:
        self.db.add(user)
        self.db.flush()
        return user
