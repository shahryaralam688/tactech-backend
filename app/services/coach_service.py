from __future__ import annotations

import json
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import Request, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.exceptions import AppError, NotFoundError, ValidationAppError
from app.core.storage import absolute_media_url, ensure_upload_dir, public_base, read_image, save_bytes
from app.db import models
from app.repositories.coach import CoachRepository
from app.schemas.coach import (
    CoachChatResponse,
    CoachConversationOut,
    CoachImageChatResponse,
    CoachMessageOut,
    CoachProviderStatusOut,
    CoachRtcIceServer,
    CoachRtcSessionOut,
    CoachVoiceTurnOut,
)
from app.services.ai.memory import CoachMemoryService
from app.services.ai.providers import (
    ChatProvider,
    EmbeddingProvider,
    STTProvider,
    TTSProvider,
    VisionProvider,
    build_chat_provider,
    build_embedding_provider,
    build_stt_provider,
    build_tts_provider,
    build_vision_provider,
    provider_status,
)

if TYPE_CHECKING:
    from app.api.deps import Principal

SYSTEM_PROMPT = """You are TacTech AI Coach — a real human coach chatting inside a fitness app.

How you talk:
- Sound natural, warm, and clear — like a coach texting a client, not a robot or textbook.
- Short readable sentences. Everyday words. Light Hinglish/Urdu/English matching the user.
- 2–5 short sentences or a few simple bullets max. No walls of text.
- Be specific using MEMORY CONTEXT (their plan, goals, logs, meals, feedback). Use their name/details when useful.
- Ask at most one short follow-up question when it helps.
- Never invent medical diagnoses. Never dump raw JSON or memory scores.
- If memory is thin, say so casually and give safe practical advice.

When they share a photo, react like a coach looking at it with them, then give 1–3 concrete tips tied to their context.
"""

VISION_SYSTEM = """You are TacTech AI Coach looking at a user's photo with them.

Talk like a supportive coach on chat: natural, clear, short.
Describe what you notice in plain language, then give 1–3 actionable tips.
Use MEMORY CONTEXT (goal, plan, calories, feedback) when relevant.
No medical diagnoses. No robotic lists unless a tiny checklist really helps.
Match the user's language (Urdu/English/Hinglish).
"""


class CoachService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.repo = CoachRepository(db)
        self.embedder: EmbeddingProvider = build_embedding_provider(settings)
        self.chat_provider: ChatProvider = build_chat_provider(settings)
        self.vision_provider: VisionProvider = build_vision_provider(settings)
        self.stt: STTProvider = build_stt_provider(settings)
        self.tts: TTSProvider = build_tts_provider(settings)
        self.memory = CoachMemoryService(db, settings, self.embedder)

    def status(self) -> CoachProviderStatusOut:
        raw = provider_status(self.settings)
        return CoachProviderStatusOut(
            provider=raw["provider"],
            chat_configured=raw["chatConfigured"],
            using_mock_fallback=raw.get("usingMockFallback", False),
            tts_provider=raw["ttsProvider"],
            embedding=raw["embedding"],
            chat_model=raw["chatModel"],
            vision_model=raw.get("visionModel"),
            supports_images=bool(raw.get("supportsImages", True)),
        )

    def list_conversations(self, principal: Principal) -> list[CoachConversationOut]:
        return [self._conversation_out(row) for row in self.repo.list_conversations(principal.user_id)]

    def create_conversation(self, principal: Principal) -> CoachConversationOut:
        row = self.repo.create_conversation(principal.user_id, principal.role)
        return self._conversation_out(row)

    def list_messages(
        self, principal: Principal, conversation_id: str, request: Request
    ) -> list[CoachMessageOut]:
        conversation = self._owned_conversation(principal, conversation_id)
        return [self._message_out(m, request) for m in self.repo.list_messages(conversation.id)]

    async def sync_memory(self, principal: Principal) -> int:
        # ensure relationships available
        user = (
            self.db.query(models.User)
            .options(
                joinedload(models.User.trainee).joinedload(models.TraineeProfile.trainer),
                joinedload(models.User.trainer),
            )
            .filter(models.User.id == principal.user_id)
            .one_or_none()
        )
        if user is None:
            raise NotFoundError("User not found.")
        return await self.memory.sync_user(principal.user_id, principal.role)

    async def chat(
        self,
        principal: Principal,
        message: str,
        conversation_id: str | None,
        request: Request,
        *,
        modality: str = "text",
        speak: bool = False,
    ) -> CoachChatResponse:
        text = (message or "").strip()
        if not text:
            raise ValidationAppError("Message cannot be empty.")
        conversation = self._resolve_conversation(principal, conversation_id)

        # Auto-sync if memory empty (first message UX)
        existing = self.db.query(models.CoachMemoryChunk).filter_by(user_id=principal.user_id).count()
        if existing == 0:
            await self.sync_memory(principal)

        citations = await self.memory.retrieve(principal.user_id, text)
        history = self.repo.list_messages(conversation.id, limit=12)
        llm_messages = self._build_messages(principal, citations, history, text)

        reply = await self.chat_provider.complete(
            llm_messages,
            temperature=self.settings.ai_chat_temperature,
            max_tokens=self.settings.ai_chat_max_tokens,
        )

        user_msg = self.repo.add_message(conversation, role="user", content=text, modality=modality)
        audio_url = None
        if speak:
            audio_url = await self._speak_and_store(reply, request)

        assistant_msg = self.repo.add_message(
            conversation,
            role="assistant",
            content=reply,
            modality="voice" if speak else "text",
            audio_url=audio_url,
            citations=citations,
        )
        return CoachChatResponse(
            conversation=self._conversation_out(conversation),
            user_message=self._message_out(user_msg, request),
            assistant_message=self._message_out(assistant_msg, request),
        )

    async def stream_chat(
        self,
        principal: Principal,
        message: str,
        conversation_id: str | None,
        request: Request,
    ) -> AsyncIterator[str]:
        text = (message or "").strip()
        if not text:
            raise ValidationAppError("Message cannot be empty.")
        conversation = self._resolve_conversation(principal, conversation_id)
        existing = self.db.query(models.CoachMemoryChunk).filter_by(user_id=principal.user_id).count()
        if existing == 0:
            await self.sync_memory(principal)

        citations = await self.memory.retrieve(principal.user_id, text)
        history = self.repo.list_messages(conversation.id, limit=12)
        llm_messages = self._build_messages(principal, citations, history, text)

        user_msg = self.repo.add_message(conversation, role="user", content=text, modality="text")
        yield json.dumps(
            {
                "event": "user",
                "conversationId": conversation.id,
                "message": self._message_out(user_msg, request).model_dump(by_alias=True, mode="json"),
            }
        )

        parts: list[str] = []
        try:
            async for delta in self.chat_provider.stream(
                llm_messages,
                temperature=self.settings.ai_chat_temperature,
                max_tokens=self.settings.ai_chat_max_tokens,
            ):
                parts.append(delta)
                yield json.dumps({"event": "delta", "text": delta})
        except AppError as exc:
            # Keep user message; surface error cleanly to SSE consumer
            yield json.dumps(
                {
                    "event": "error",
                    "detail": exc.message,
                    "code": exc.code or "AI_ERROR",
                    "statusCode": exc.status_code,
                    "conversationId": conversation.id,
                }
            )
            return

        reply = "".join(parts).strip() or "Sorry — I could not generate a reply."
        assistant_msg = self.repo.add_message(
            conversation,
            role="assistant",
            content=reply,
            modality="text",
            citations=citations,
        )
        yield json.dumps(
            {
                "event": "done",
                "message": self._message_out(assistant_msg, request).model_dump(by_alias=True, mode="json"),
                "citations": citations,
            }
        )

    async def voice_turn(
        self,
        principal: Principal,
        audio: UploadFile,
        conversation_id: str | None,
        request: Request,
        *,
        speak: bool = True,
    ) -> CoachVoiceTurnOut:
        data = await audio.read()
        if not data:
            raise ValidationAppError("Audio file is empty.")
        if len(data) > self.settings.max_upload_bytes * 2:
            raise ValidationAppError("Audio file is too large.")
        transcript = await self.stt.transcribe(
            data,
            audio.filename or "audio.m4a",
            audio.content_type,
        )
        chat = await self.chat(
            principal,
            transcript,
            conversation_id,
            request,
            modality="voice",
            speak=speak,
        )
        return CoachVoiceTurnOut(
            conversation=chat.conversation,
            transcript=transcript,
            user_message=chat.user_message,
            assistant_message=chat.assistant_message,
            audio_url=chat.assistant_message.audio_url,
        )

    async def chat_with_image(
        self,
        principal: Principal,
        image: UploadFile,
        message: str | None,
        conversation_id: str | None,
        request: Request,
    ) -> CoachImageChatResponse:
        caption = (message or "").strip() or "Please analyze this photo and give coaching feedback."
        image_bytes, extension = await read_image(image, self.settings)
        stored = save_bytes(self.settings, "coach/images", image_bytes, extension)
        conversation = self._resolve_conversation(principal, conversation_id)

        existing = self.db.query(models.CoachMemoryChunk).filter_by(user_id=principal.user_id).count()
        if existing == 0:
            await self.sync_memory(principal)

        citations = await self.memory.retrieve(principal.user_id, caption)
        memory_block = "\n".join(
            f"- {c['content']}" for c in citations
        ) or "- (no saved context yet)"
        system = (
            f"{VISION_SYSTEM}\n\nUSER ROLE: {principal.role}\n"
            f"WHAT YOU KNOW ABOUT THIS USER:\n{memory_block}"
        )
        analysis = await self.vision_provider.analyze(
            system_prompt=system,
            user_text=caption,
            image_bytes=image_bytes,
            content_type=image.content_type,
            temperature=self.settings.ai_chat_temperature,
            max_tokens=self.settings.ai_chat_max_tokens,
        )

        user_msg = self.repo.add_message(
            conversation,
            role="user",
            content=caption,
            modality="image",
            image_url=stored,
        )
        assistant_msg = self.repo.add_message(
            conversation,
            role="assistant",
            content=analysis,
            modality="text",
            citations=citations,
        )
        # Persist a short memory crumb so later chat can reference this photo analysis
        try:
            vectors = await self.embedder.embed([f"Shared photo analysis: {analysis[:500]}"])
            from datetime import datetime, timezone
            from uuid import uuid4

            self.db.add(
                models.CoachMemoryChunk(
                    id=str(uuid4()),
                    user_id=principal.user_id,
                    source_type="shared_image",
                    source_id=user_msg.id,
                    content=f"User shared an image with caption '{caption}'. Analysis: {analysis[:700]}",
                    embedding=vectors[0],
                    metadata_json={"kind": "image", "imageUrl": stored},
                    updated_at=datetime.now(timezone.utc),
                )
            )
            self.db.commit()
        except Exception:
            self.db.rollback()

        return CoachImageChatResponse(
            conversation=self._conversation_out(conversation),
            user_message=self._message_out(user_msg, request),
            assistant_message=self._message_out(assistant_msg, request),
            image_analysis=analysis,
        )

    def create_rtc_session(
        self, principal: Principal, conversation_id: str | None, request: Request
    ) -> CoachRtcSessionOut:
        if conversation_id:
            self._owned_conversation(principal, conversation_id)
        session = self.repo.create_rtc_session(principal.user_id, conversation_id)
        return self._rtc_out(session, request)

    def get_rtc_session(self, principal: Principal, session_id: str, request: Request) -> CoachRtcSessionOut:
        session = self.repo.get_rtc_session(session_id, principal.user_id)
        if session is None:
            raise NotFoundError("RTC session not found.")
        return self._rtc_out(session, request)

    def ice_servers(self) -> list[CoachRtcIceServer]:
        urls = [u.strip() for u in self.settings.webrtc_stun_urls.split(",") if u.strip()]
        return [CoachRtcIceServer(urls=urls)]

    async def _speak_and_store(self, text: str, request: Request) -> str | None:
        """Best-effort TTS. Never fail the chat/voice turn if speech synthesis is down."""
        try:
            audio_bytes, extension = await self.tts.synthesize(text)
        except Exception as exc:
            from app.core.logging import get_logger

            get_logger("tactech.coach").warning("tts_skipped", error=str(exc)[:240])
            return None
        if not audio_bytes:
            return None
        ensure_upload_dir(self.settings)
        stored = save_bytes(self.settings, "coach/voice", audio_bytes, extension)
        return absolute_media_url(request, self.settings, stored)

    def _build_messages(
        self,
        principal: Principal,
        citations: list[dict],
        history: list[models.CoachMessage],
        user_text: str,
    ) -> list[dict[str, str]]:
        memory_block = "\n".join(
            f"- {c['content']}" for c in citations
        ) or "- (no saved context yet — keep advice practical and ask one clarifying question)"
        system = (
            f"{SYSTEM_PROMPT}\n\nUSER ROLE: {principal.role}\n"
            f"WHAT YOU KNOW ABOUT THIS USER:\n{memory_block}"
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for msg in history[-10:]:
            if msg.role in {"user", "assistant"}:
                messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_text})
        return messages

    def _resolve_conversation(
        self, principal: Principal, conversation_id: str | None
    ) -> models.CoachConversation:
        if conversation_id:
            return self._owned_conversation(principal, conversation_id)
        return self.repo.create_conversation(principal.user_id, principal.role)

    def _owned_conversation(self, principal: Principal, conversation_id: str) -> models.CoachConversation:
        row = self.repo.get_conversation(conversation_id, principal.user_id)
        if row is None:
            raise NotFoundError("Conversation not found.")
        return row

    def _conversation_out(self, row: models.CoachConversation) -> CoachConversationOut:
        return CoachConversationOut(
            id=row.id,
            title=row.title,
            role=row.role,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _message_out(self, row: models.CoachMessage, request: Request) -> CoachMessageOut:
        return CoachMessageOut(
            id=row.id,
            conversation_id=row.conversation_id,
            role=row.role,
            content=row.content,
            modality=row.modality,
            audio_url=absolute_media_url(request, self.settings, row.audio_url),
            image_url=absolute_media_url(request, self.settings, row.image_url),
            citations=row.citations,
            created_at=row.created_at,
        )

    def _rtc_out(self, session: models.CoachRtcSession, request: Request) -> CoachRtcSessionOut:
        base = public_base(request, self.settings)
        # Prefer wss when public URL is https
        ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
        return CoachRtcSessionOut(
            id=session.id,
            conversation_id=session.conversation_id,
            status=session.status,
            ice_servers=self.ice_servers(),
            signaling_path=f"{ws_base}/coach/rtc/ws/{session.id}",
            created_at=session.created_at,
        )
