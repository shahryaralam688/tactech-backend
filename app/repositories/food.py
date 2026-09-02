from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class FoodRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> list[models.FoodKnowledge]:
        stmt = select(models.FoodKnowledge).order_by(models.FoodKnowledge.name)
        return list(self.db.execute(stmt).scalars().all())

    def lookup(self, query: str) -> models.FoodKnowledge | None:
        needle = query.strip().lower()
        if not needle:
            return None
        for item in self.list_all():
            name = item.name.lower()
            keywords = [str(k).lower() for k in item.keywords]
            if needle in name or any(needle in k or k in needle for k in keywords):
                return item
        return None

    def add(self, food: models.FoodKnowledge) -> models.FoodKnowledge:
        self.db.add(food)
        self.db.flush()
        return food
