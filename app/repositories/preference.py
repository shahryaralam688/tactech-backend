from sqlalchemy.orm import Session

from app.db import models


class PreferenceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: str) -> models.UserPreferences | None:
        return self.db.get(models.UserPreferences, user_id)

    def add(self, prefs: models.UserPreferences) -> models.UserPreferences:
        self.db.add(prefs)
        self.db.flush()
        return prefs
