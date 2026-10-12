from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request, UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationAppError
from app.core.storage import absolute_media_url, read_image, save_bytes
from app.db import models
from app.repositories.support import SupportRepository
from app.schemas.support import SupportConversationOut, SupportMessageOut


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SupportService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.support = SupportRepository(db)

    def get_or_create_open(self, user_id: str) -> SupportConversationOut:
        conversation = self.support.latest_open(user_id)
        if conversation is None:
            conversation = self._create(user_id)
        return self._conversation_out(conversation)

    def create_conversation(self, user_id: str) -> SupportConversationOut:
        return self._conversation_out(self._create(user_id))

    def list_messages(
        self,
        user_id: str,
        conversation_id: str,
        after: str | None,
        request: Request,
    ) -> list[SupportMessageOut]:
        conversation = self._owned(user_id, conversation_id)
        after_message = None
        if after:
            after_message = self.support.get_message(after)
            if after_message is None or after_message.conversation_id != conversation.id:
                raise NotFoundError("Message not found.")
        return [
            self._message_out(item, request)
            for item in self.support.list_messages(conversation.id, after_message)
        ]

    async def add_message(
        self,
        user_id: str,
        conversation_id: str,
        text: str | None,
        file: UploadFile | None,
        request: Request,
    ) -> SupportMessageOut:
        conversation = self._owned(user_id, conversation_id)
        cleaned = (text or "").strip() or None
        attachment = None
        if file is not None and file.filename:
            data, extension = await read_image(file, self.settings)
            attachment = save_bytes(self.settings, f"support/{conversation.id}", data, extension)
        if not cleaned and not attachment:
            raise ValidationAppError("Write a message or attach a photo.")
        now = _utc_now()
        message = models.SupportMessage(
            id=str(uuid4()),
            conversation_id=conversation.id,
            sender="user",
            text=cleaned,
            attachment_url=attachment,
            created_at=now,
        )
        self.support.add_message(message)
        conversation.updated_at = now
        return self._message_out(message, request)

    def _create(self, user_id: str) -> models.SupportConversation:
        now = _utc_now()
        conversation = models.SupportConversation(
            id=str(uuid4()),
            user_id=user_id,
            status="open",
            created_at=now,
            updated_at=now,
        )
        self.support.add_conversation(conversation)
        self.support.add_message(
            models.SupportMessage(
                id=str(uuid4()),
                conversation_id=conversation.id,
                sender="system",
                text="Thanks for contacting TacTech support. Tell us what you need help with.",
                attachment_url=None,
                created_at=now,
            )
        )
        return conversation

    def _owned(self, user_id: str, conversation_id: str) -> models.SupportConversation:
        conversation = self.support.get_conversation(conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        if conversation.user_id != user_id:
            raise ForbiddenError("You can only access your own conversations.")
        return conversation

    def _conversation_out(self, conversation: models.SupportConversation) -> SupportConversationOut:
        return SupportConversationOut(
            id=conversation.id,
            status=conversation.status,
            updated_at=conversation.updated_at,
        )

    def _message_out(self, message: models.SupportMessage, request: Request) -> SupportMessageOut:
        sender = message.sender
        # iOS expects user | support | agent (map legacy system → support)
        if sender == "system":
            sender = "support"
        return SupportMessageOut(
            id=message.id,
            conversation_id=message.conversation_id,
            sender=sender,
            text=message.text,
            attachment_url=absolute_media_url(request, self.settings, message.attachment_url),
            created_at=message.created_at,
        )
