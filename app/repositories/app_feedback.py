from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class AppFeedbackRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, item: models.AppFeedback) -> models.AppFeedback:
        self.db.add(item)
        self.db.flush()
        return item

    def list_for_user(self, user_id: str) -> list[models.AppFeedback]:
        stmt = (
            select(models.AppFeedback)
            .where(models.AppFeedback.user_id == user_id)
            .order_by(models.AppFeedback.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())
