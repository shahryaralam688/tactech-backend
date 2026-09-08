from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class SupportRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_conversation(self, conversation_id: str) -> models.SupportConversation | None:
        return self.db.get(models.SupportConversation, conversation_id)

    def latest_open(self, user_id: str) -> models.SupportConversation | None:
        stmt = (
            select(models.SupportConversation)
            .where(
                models.SupportConversation.user_id == user_id,
                models.SupportConversation.status == "open",
            )
            .order_by(models.SupportConversation.updated_at.desc())
        )
        return self.db.execute(stmt).scalars().first()

    def add_conversation(self, conversation: models.SupportConversation) -> models.SupportConversation:
        self.db.add(conversation)
        self.db.flush()
        return conversation

    def get_message(self, message_id: str) -> models.SupportMessage | None:
        return self.db.get(models.SupportMessage, message_id)

    def list_messages(
        self,
        conversation_id: str,
        after: models.SupportMessage | None = None,
    ) -> list[models.SupportMessage]:
        stmt = (
            select(models.SupportMessage)
            .where(models.SupportMessage.conversation_id == conversation_id)
            .order_by(models.SupportMessage.created_at.asc())
        )
        if after is not None:
            stmt = stmt.where(models.SupportMessage.created_at > after.created_at)
        return list(self.db.execute(stmt).scalars().all())

    def add_message(self, message: models.SupportMessage) -> models.SupportMessage:
        self.db.add(message)
        self.db.flush()
        return message
