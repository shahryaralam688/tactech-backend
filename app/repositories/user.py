from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: str) -> models.User | None:
        return self.db.get(models.User, user_id)

    def get_by_email(self, email: str) -> models.User | None:
        stmt = select(models.User).where(models.User.email == email)
        return self.db.execute(stmt).scalar_one_or_none()

    def add(self, user: models.User) -> models.User:
        self.db.add(user)
        self.db.flush()
        return user
