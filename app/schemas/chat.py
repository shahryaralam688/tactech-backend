from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class ChatThreadOut(APIModel):
    id: str
    peer_user_id: str
    peer_name: str
    peer_avatar_url: str | None = None
    last_message_preview: str | None = None
    last_message_at: datetime | None = None
    unread_count: int = 0
    peer_role: str
    created_at: datetime
    updated_at: datetime


class ChatThreadCreateRequest(APIModel):
    """Canonical: peerUserId = User.id. Also accepts profile ids for iOS roster quirks."""

    peer_user_id: str | None = Field(default=None, max_length=64)
    peer_trainee_profile_id: str | None = Field(default=None, max_length=64)
    peer_trainer_profile_id: str | None = Field(default=None, max_length=64)


class ChatReactionOut(APIModel):
    emoji: str
    user_id: str
    created_at: datetime


class ChatMessageOut(APIModel):
    id: str
    thread_id: str
    sender_user_id: str
    sender_role: str
    kind: str = "text"
    text: str | None = None
    attachment_url: str | None = None
    attachment_type: str | None = None
    duration_seconds: int | None = None
    call_outcome: str | None = None
    client_id: str | None = None
    created_at: datetime
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    played_at: datetime | None = None
    reply_to_message_id: str | None = None
    reply_to_text: str | None = None
    reply_to_sender_name: str | None = None
    reactions: list[ChatReactionOut] = Field(default_factory=list)
    edited_at: datetime | None = None
    deleted_for_everyone_at: datetime | None = None


class ChatMessageCreateRequest(APIModel):
    text: str | None = None
    client_id: str | None = Field(default=None, max_length=64)
    kind: str | None = Field(default=None, max_length=16)
    call_outcome: str | None = Field(default=None, max_length=120)
    duration_seconds: int | None = None
    reply_to_message_id: str | None = Field(default=None, max_length=64)


class ChatMessageEditRequest(APIModel):
    text: str = Field(min_length=1, max_length=4000)


class ChatReactRequest(APIModel):
    emoji: str = Field(min_length=1, max_length=32)


class ChatMessagePage(APIModel):
    items: list[ChatMessageOut]
    next_cursor: str | None = None


class ChatThreadPage(APIModel):
    items: list[ChatThreadOut]
    next_cursor: str | None = None


class ChatReadRequest(APIModel):
    up_to_message_id: str = Field(min_length=1, max_length=64)


class ChatReadOut(APIModel):
    thread_id: str
    up_to_message_id: str
    reader_user_id: str
    unread_count: int


class ChatDeliveredRequest(APIModel):
    up_to_message_id: str = Field(min_length=1, max_length=64)


class ChatDeliveredOut(APIModel):
    thread_id: str
    up_to_message_id: str
    delivered_by_user_id: str
    delivered_at: datetime


class ChatPlayedOut(APIModel):
    thread_id: str
    message_id: str
    played_by_user_id: str
    played_at: datetime


class ChatReactionEventOut(APIModel):
    thread_id: str
    message_id: str
    reactions: list[ChatReactionOut]


class ChatIceServer(APIModel):
    urls: list[str]
    username: str | None = None
    credential: str | None = None


class ChatIceServersOut(APIModel):
    ice_servers: list[ChatIceServer]


class ChatRtcSessionCreateRequest(APIModel):
    thread_id: str = Field(min_length=1, max_length=64)


class ChatRtcSessionOut(APIModel):
    id: str
    thread_id: str
    signaling_path: str
    ice_servers: list[ChatIceServer]
    created_at: datetime


class ChatIncomingCallOut(APIModel):
    thread_id: str
    session_id: str
    from_user_id: str
    from_name: str
    signaling_path: str
    created_at: datetime


class ChatIncomingCallsOut(APIModel):
    items: list[ChatIncomingCallOut]
