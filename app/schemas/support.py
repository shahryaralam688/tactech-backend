from datetime import datetime

from app.schemas.common import APIModel
from app.schemas.requests import RequestModel


class SupportConversationOut(APIModel):
    id: str
    status: str
    updated_at: datetime


class SupportMessageOut(APIModel):
    id: str
    conversation_id: str
    sender: str
    text: str | None = None
    attachment_url: str | None = None
    created_at: datetime


class SupportMessageCreate(RequestModel):
    text: str | None = None
