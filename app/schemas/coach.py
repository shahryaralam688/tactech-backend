from datetime import datetime

from app.schemas.common import APIModel


class CoachConversationOut(APIModel):
    id: str
    title: str
    role: str
    created_at: datetime
    updated_at: datetime


class CoachMessageOut(APIModel):
    id: str
    conversation_id: str
    role: str
    content: str
    modality: str
    audio_url: str | None = None
    image_url: str | None = None
    citations: list[dict] | None = None
    created_at: datetime


class CoachChatRequest(APIModel):
    message: str
    conversation_id: str | None = None
    stream: bool = False


class CoachImageChatResponse(APIModel):
    conversation: CoachConversationOut
    user_message: CoachMessageOut
    assistant_message: CoachMessageOut
    image_analysis: str | None = None


class CoachChatResponse(APIModel):
    conversation: CoachConversationOut
    user_message: CoachMessageOut
    assistant_message: CoachMessageOut


class CoachMemorySyncOut(APIModel):
    chunk_count: int
    user_id: str


class CoachMemoryHit(APIModel):
    id: str
    source_type: str
    source_id: str | None = None
    content: str
    score: float


class CoachVoiceTurnOut(APIModel):
    conversation: CoachConversationOut
    transcript: str
    user_message: CoachMessageOut
    assistant_message: CoachMessageOut
    audio_url: str | None = None


class CoachProviderStatusOut(APIModel):
    provider: str
    chat_configured: bool
    using_mock_fallback: bool = False
    tts_provider: str
    embedding: str
    chat_model: str
    vision_model: str | None = None
    supports_images: bool = True


class CoachRtcIceServer(APIModel):
    urls: list[str]


class CoachRtcSessionOut(APIModel):
    id: str
    conversation_id: str | None = None
    status: str
    ice_servers: list[CoachRtcIceServer]
    signaling_path: str
    created_at: datetime


class CoachRtcSignalIn(APIModel):
    type: str  # offer | answer | ice | hangup
    sdp: str | None = None
    candidate: dict | None = None
