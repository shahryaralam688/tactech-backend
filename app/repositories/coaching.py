from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class CoachingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_feedback(self, trainee_id: str) -> list[models.TrainerFeedback]:
        stmt = (
            select(models.TrainerFeedback)
            .where(models.TrainerFeedback.trainee_id == trainee_id)
            .order_by(models.TrainerFeedback.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_feedback(self, item: models.TrainerFeedback) -> models.TrainerFeedback:
        self.db.add(item)
        self.db.flush()
        return item

    def list_form_reports(self, trainee_id: str) -> list[models.FormReport]:
        stmt = (
            select(models.FormReport)
            .where(models.FormReport.trainee_id == trainee_id)
            .order_by(models.FormReport.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_form_report(self, report: models.FormReport) -> models.FormReport:
        self.db.add(report)
        self.db.flush()
        return report
