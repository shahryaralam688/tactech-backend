from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse

from app.api.deps import Principal, get_coach_service, get_principal, get_settings
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import decode_token
from app.db.session import SessionLocal
from app.repositories.coach import CoachRepository
from app.schemas.coach import (
    CoachChatRequest,
    CoachConversationOut,
    CoachImageChatResponse,
    CoachMemorySyncOut,
    CoachMessageOut,
    CoachProviderStatusOut,
    CoachRtcIceServer,
    CoachRtcSessionOut,
    CoachVoiceTurnOut,
)
from app.services.coach_service import CoachService

router = APIRouter(prefix="/coach", tags=["ai-coach"])

# In-memory WebRTC signaling rooms (single-process demo). Use Redis pub/sub for multi-worker later.
_rtc_rooms: dict[str, set[WebSocket]] = {}
_rtc_lock = asyncio.Lock()


@router.get("/status", response_model=CoachProviderStatusOut)
def coach_status(service: Annotated[CoachService, Depends(get_coach_service)]) -> CoachProviderStatusOut:
    return service.status()


@router.post("/memory/sync", response_model=CoachMemorySyncOut)
async def sync_memory(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[CoachService, Depends(get_coach_service)],
) -> CoachMemorySyncOut:
    count = await service.sync_memory(principal)
    return CoachMemorySyncOut(chunk_count=count, user_id=principal.user_id)


@router.get("/conversations", response_model=list[CoachConversationOut])
def list_conversations(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[CoachService, Depends(get_coach_service)],
) -> list[CoachConversationOut]:
    return service.list_conversations(principal)


@router.post("/conversations", response_model=CoachConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[CoachService, Depends(get_coach_service)],
) -> CoachConversationOut:
    return service.create_conversation(principal)


@router.get("/conversations/{conversation_id}/messages", response_model=list[CoachMessageOut])
def list_messages(
    conversation_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[CoachService, Depends(get_coach_service)],
) -> list[CoachMessageOut]:
    return service.list_messages(principal, conversation_id, request)


@router.post("/chat")
async def chat(
    payload: CoachChatRequest,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[CoachService, Depends(get_coach_service)],
):
    if payload.stream:

        async def event_gen():
            try:
                async for chunk in service.stream_chat(
                    principal, payload.message, payload.conversation_id, request
                ):
                    yield f"data: {chunk}\n\n"
            except AppError as exc:
                # Response already started (SSE) — send error event instead of raising
                payload_err = {
                    "event": "error",
                    "detail": exc.message,
                    "code": exc.code or "AI_ERROR",
                    "statusCode": exc.status_code,
                }
                yield f"data: {json.dumps(payload_err)}\n\n"
            except Exception:
                payload_err = {
                    "event": "error",
                    "detail": "AI coach failed unexpectedly. Try again.",
                    "code": "AI_ERROR",
                    "statusCode": 500,
                }
                yield f"data: {json.dumps(payload_err)}\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream")
    return await service.chat(principal, payload.message, payload.conversation_id, request)


@router.post("/chat/image", response_model=CoachImageChatResponse, status_code=status.HTTP_201_CREATED)
async def chat_with_image(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[CoachService, Depends(get_coach_service)],
    image: UploadFile = File(...),
    message: str | None = Form(default=None),
    conversation_id: str | None = Form(default=None),
) -> CoachImageChatResponse:
    """Share a JPEG/PNG photo for AI coaching analysis (form, meal, progress, etc.)."""
    return await service.chat_with_image(principal, image, message, conversation_id, request)


@router.post("/voice/turn", response_model=CoachVoiceTurnOut)
async def voice_turn(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[CoachService, Depends(get_coach_service)],
    audio: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
    speak: bool = Form(default=True),
) -> CoachVoiceTurnOut:
    return await service.voice_turn(principal, audio, conversation_id, request, speak=speak)


@router.get("/rtc/ice-servers", response_model=list[CoachRtcIceServer])
def ice_servers(service: Annotated[CoachService, Depends(get_coach_service)]) -> list[CoachRtcIceServer]:
    return service.ice_servers()


@router.post("/rtc/sessions", response_model=CoachRtcSessionOut, status_code=status.HTTP_201_CREATED)
def create_rtc_session(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[CoachService, Depends(get_coach_service)],
    conversation_id: str | None = Query(default=None),
) -> CoachRtcSessionOut:
    return service.create_rtc_session(principal, conversation_id, request)


@router.get("/rtc/sessions/{session_id}", response_model=CoachRtcSessionOut)
def get_rtc_session(
    session_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[CoachService, Depends(get_coach_service)],
) -> CoachRtcSessionOut:
    return service.get_rtc_session(principal, session_id, request)


@router.websocket("/rtc/ws/{session_id}")
async def rtc_signaling(
    websocket: WebSocket,
    session_id: str,
    token: str | None = Query(default=None),
) -> None:
    """WebRTC signaling channel: relay offer/answer/ice between peers in a session room.

    Message JSON shapes:
      {"type":"offer","sdp":"..."}
      {"type":"answer","sdp":"..."}
      {"type":"ice","candidate":{...}}
      {"type":"hangup"}
      {"type":"voice_hint","text":"..."}  # optional text cue while speaking
    """
    settings = get_settings()
    await websocket.accept()
    user_id = await _ws_user_id(websocket, settings, token)
    if user_id is None:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        repo = CoachRepository(db)
        session = repo.get_rtc_session(session_id, user_id)
        if session is None or session.status != "open":
            await websocket.send_json({"type": "error", "detail": "RTC session not found."})
            await websocket.close(code=4404)
            return
    finally:
        db.close()

    async with _rtc_lock:
        room = _rtc_rooms.setdefault(session_id, set())
        room.add(websocket)

    await websocket.send_json(
        {
            "type": "joined",
            "sessionId": session_id,
            "peers": max(len(_rtc_rooms.get(session_id, set())) - 1, 0),
            "iceServers": [{"urls": [u.strip() for u in settings.webrtc_stun_urls.split(",") if u.strip()]}],
        }
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "Invalid JSON."})
                continue
            msg_type = payload.get("type")
            if msg_type not in {"offer", "answer", "ice", "hangup", "voice_hint"}:
                await websocket.send_json({"type": "error", "detail": "Unsupported signal type."})
                continue
            payload["fromUserId"] = user_id
            await _broadcast(session_id, websocket, payload)
            if msg_type == "hangup":
                break
    except WebSocketDisconnect:
        pass
    finally:
        async with _rtc_lock:
            room = _rtc_rooms.get(session_id)
            if room and websocket in room:
                room.remove(websocket)
            if room is not None and not room:
                _rtc_rooms.pop(session_id, None)


async def _broadcast(session_id: str, sender: WebSocket, payload: dict[str, Any]) -> None:
    async with _rtc_lock:
        peers = list(_rtc_rooms.get(session_id, set()))
    dead: list[WebSocket] = []
    for peer in peers:
        if peer is sender:
            continue
        try:
            await peer.send_json(payload)
        except Exception:
            dead.append(peer)
    if dead:
        async with _rtc_lock:
            room = _rtc_rooms.get(session_id)
            if room:
                for peer in dead:
                    room.discard(peer)


async def _ws_user_id(websocket: WebSocket, settings: Settings, token: str | None) -> str | None:
    auth = websocket.headers.get("authorization")
    raw = token
    if not raw and auth and auth.lower().startswith("bearer "):
        raw = auth.split(" ", 1)[1].strip()
    if not raw:
        return None
    try:
        payload = decode_token(raw, settings)
        if payload.get("type") != "access":
            return None
        return payload.get("sub")
    except Exception:
        return None
