from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from redis import Redis
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.requests import Request as StarletteRequest

from app.api.deps import (
    Principal,
    enforce_chat_media_rate_limit,
    enforce_chat_rate_limit,
    enforce_chat_rtc_rate_limit,
    get_principal,
    get_redis,
    get_settings,
)
from app.core.config import Settings
from app.core.exceptions import RateLimitError
from app.core.redis import RateLimiter
from app.core.security import decode_token
from app.db.session import SessionLocal, get_db
from app.realtime.chat_hub import chat_hub
from app.repositories.chat import ChatRepository
from app.schemas.chat import (
    ChatDeliveredOut,
    ChatDeliveredRequest,
    ChatIceServersOut,
    ChatIncomingCallsOut,
    ChatMessageCreateRequest,
    ChatMessageEditRequest,
    ChatMessageOut,
    ChatMessagePage,
    ChatPlayedOut,
    ChatReactRequest,
    ChatReactionEventOut,
    ChatReadOut,
    ChatReadRequest,
    ChatRtcSessionCreateRequest,
    ChatRtcSessionOut,
    ChatThreadCreateRequest,
    ChatThreadOut,
    ChatThreadPage,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])

_rtc_rooms: dict[str, set[WebSocket]] = {}
_rtc_lock = asyncio.Lock()
_SIGNAL_TYPES = {"offer", "answer", "ice-candidate", "ice", "hangup", "ping"}


def get_chat_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatService:
    return ChatService(db, settings, hub=chat_hub)


@router.get("/threads", response_model=ChatThreadPage)
def list_threads(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatThreadPage:
    return service.list_threads(principal, request)


@router.post("/threads", response_model=ChatThreadOut)
def create_thread(
    payload: ChatThreadCreateRequest,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatThreadOut:
    out, created = service.find_or_create_thread(
        principal,
        request,
        peer_user_id=payload.peer_user_id,
        peer_trainee_profile_id=payload.peer_trainee_profile_id,
        peer_trainer_profile_id=payload.peer_trainer_profile_id,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return out


@router.get("/threads/{thread_id}/messages", response_model=ChatMessagePage)
def list_messages(
    thread_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> ChatMessagePage:
    return service.list_messages(principal, thread_id, request, cursor=cursor, limit=limit)


@router.post(
    "/threads/{thread_id}/messages",
    response_model=ChatMessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    thread_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    redis_client: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(enforce_chat_rate_limit)] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChatMessageOut:
    """JSON text / call_event, or multipart media (same path)."""
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        allowed, retry_after = RateLimiter(redis_client).check(
            f"chat:media:{principal.user_id}",
            settings.chat_media_rate_limit,
            settings.chat_rate_window_seconds,
        )
        if not allowed:
            raise RateLimitError(
                "Too many media uploads. Wait a moment, then try again.",
                retry_after=retry_after,
            )
        form = await request.form()
        file = form.get("file")
        if isinstance(file, (list, tuple)):
            file = file[0] if file else None
        upload: UploadFile | None = None
        if file is not None and hasattr(file, "read") and hasattr(file, "filename"):
            upload = file  # type: ignore[assignment]
        text = form.get("text")
        client_id = form.get("clientId") or form.get("client_id") or idempotency_key
        kind = form.get("kind")
        attachment_type = form.get("attachmentType") or form.get("attachment_type")
        reply_to = form.get("replyToMessageId") or form.get("reply_to_message_id")
        duration_raw = form.get("durationSeconds") or form.get("duration_seconds")
        duration_seconds = None
        if duration_raw not in (None, ""):
            try:
                duration_seconds = int(str(duration_raw))
            except ValueError:
                duration_seconds = None
        return await service.send_message(
            principal,
            thread_id,
            request,
            text=str(text) if text is not None else None,
            client_id=str(client_id) if client_id else None,
            file=upload,
            kind=str(kind) if kind else None,
            duration_seconds=duration_seconds,
            attachment_type_hint=str(attachment_type) if attachment_type else None,
            reply_to_message_id=str(reply_to) if reply_to else None,
        )

    body = await request.json()
    payload = ChatMessageCreateRequest.model_validate(body)
    return await service.send_message(
        principal,
        thread_id,
        request,
        text=payload.text,
        client_id=payload.client_id or idempotency_key,
        file=None,
        kind=payload.kind,
        call_outcome=payload.call_outcome,
        duration_seconds=payload.duration_seconds,
        reply_to_message_id=payload.reply_to_message_id,
    )


@router.post(
    "/threads/{thread_id}/messages/upload",
    response_model=ChatMessageOut,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
async def send_message_multipart_alias(
    thread_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    _: Annotated[None, Depends(enforce_chat_media_rate_limit)] = None,
    text: str | None = Form(default=None),
    client_id: str | None = Form(default=None),
    clientId: str | None = Form(default=None),
    attachment_type: str | None = Form(default=None),
    attachmentType: str | None = Form(default=None),
    duration_seconds: int | None = Form(default=None),
    durationSeconds: int | None = Form(default=None),
    kind: str | None = Form(default=None),
    reply_to_message_id: str | None = Form(default=None),
    replyToMessageId: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChatMessageOut:
    """Alias for multipart; prefer POST /chat/threads/{id}/messages."""
    return await service.send_message(
        principal,
        thread_id,
        request,
        text=text,
        client_id=client_id or clientId or idempotency_key,
        file=file,
        kind=kind,
        duration_seconds=duration_seconds if duration_seconds is not None else durationSeconds,
        attachment_type_hint=attachment_type or attachmentType,
        reply_to_message_id=reply_to_message_id or replyToMessageId,
    )


@router.post("/threads/{thread_id}/read", response_model=ChatReadOut)
async def mark_read(
    thread_id: str,
    payload: ChatReadRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatReadOut:
    return await service.mark_read(principal, thread_id, payload.up_to_message_id)


@router.post("/threads/{thread_id}/delivered", response_model=ChatDeliveredOut)
async def mark_delivered(
    thread_id: str,
    payload: ChatDeliveredRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatDeliveredOut:
    return await service.mark_delivered(principal, thread_id, payload.up_to_message_id)


@router.post(
    "/threads/{thread_id}/messages/{message_id}/played",
    response_model=ChatPlayedOut,
)
async def mark_played(
    thread_id: str,
    message_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatPlayedOut:
    return await service.mark_played(principal, thread_id, message_id)


@router.post(
    "/threads/{thread_id}/messages/{message_id}/reactions",
    response_model=ChatReactionEventOut,
)
async def add_reaction(
    thread_id: str,
    message_id: str,
    payload: ChatReactRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatReactionEventOut:
    return await service.react(principal, thread_id, message_id, payload.emoji)


@router.delete(
    "/threads/{thread_id}/messages/{message_id}/reactions/{emoji}",
    response_model=ChatReactionEventOut,
)
async def remove_reaction(
    thread_id: str,
    message_id: str,
    emoji: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatReactionEventOut:
    return await service.unreact(principal, thread_id, message_id, emoji)


@router.patch(
    "/threads/{thread_id}/messages/{message_id}",
    response_model=ChatMessageOut,
)
async def edit_message(
    thread_id: str,
    message_id: str,
    payload: ChatMessageEditRequest,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatMessageOut:
    return await service.edit_message(principal, thread_id, message_id, payload.text, request)


@router.delete(
    "/threads/{thread_id}/messages/{message_id}",
    response_model=None,
)
async def delete_message(
    thread_id: str,
    message_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    scope: str = Query(default="everyone"),
) -> ChatMessageOut | Response:
    out = await service.delete_message(
        principal, thread_id, message_id, scope=scope, request=request
    )
    if out is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return out

@router.get("/rtc/ice-servers", response_model=ChatIceServersOut)
def ice_servers(service: Annotated[ChatService, Depends(get_chat_service)]) -> ChatIceServersOut:
    return service.ice_servers()


@router.get("/rtc/incoming", response_model=ChatIncomingCallsOut)
def list_incoming_calls(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatIncomingCallsOut:
    """Active ringing sessions for the current user (REST fallback / cold start)."""
    return service.list_incoming_calls(principal, request)


@router.post("/rtc/sessions", response_model=ChatRtcSessionOut, status_code=status.HTTP_201_CREATED)
async def create_rtc_session(
    payload: ChatRtcSessionCreateRequest,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    _: Annotated[None, Depends(enforce_chat_rtc_rate_limit)] = None,
) -> ChatRtcSessionOut:
    return await service.create_rtc_session(principal, payload.thread_id, request)


@router.get("/rtc/sessions/{session_id}", response_model=ChatRtcSessionOut)
def get_rtc_session(
    session_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatRtcSessionOut:
    return service.get_rtc_session(principal, session_id, request)


@router.websocket("/rtc/sessions/{session_id}/signal")
async def chat_rtc_signal(
    websocket: WebSocket,
    session_id: str,
    token: str | None = Query(default=None),
) -> None:
    """Peer-to-peer WebRTC signaling for trainer↔trainee video calls."""
    settings = get_settings()
    await websocket.accept()
    user_id = await _ws_user_id(websocket, settings, token)
    if user_id is None:
        await websocket.send_json(
            {"type": "error", "detail": "Authentication required.", "code": "UNAUTHORIZED"}
        )
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        repo = ChatRepository(db)
        session = repo.get_rtc_session(session_id)
        if session is None or session.status != "active":
            await websocket.send_json(
                {"type": "error", "detail": "Call session not found.", "code": "NOT_FOUND"}
            )
            await websocket.close(code=4404)
            return
        thread = repo.get_thread(session.thread_id)
        if thread is None or user_id not in {thread.trainer_user_id, thread.trainee_user_id}:
            await websocket.send_json(
                {"type": "error", "detail": "You do not have access to this call.", "code": "FORBIDDEN"}
            )
            await websocket.close(code=4403)
            return
    finally:
        db.close()

    async with _rtc_lock:
        room = _rtc_rooms.setdefault(session_id, set())
        room.add(websocket)

    joined = {"type": "joined", "sessionId": session_id, "userId": user_id}
    # Tell the connecting peer…
    await websocket.send_json(joined)
    # …and every other peer already in the room (caller stops “Calling…” / ringback).
    await _broadcast(session_id, websocket, joined)

    hangup_reason = "ended"
    should_persist_hangup = False
    idle = max(30, int(settings.chat_rtc_idle_seconds))
    max_call = max(60, int(settings.chat_rtc_max_seconds))
    started = asyncio.get_event_loop().time()

    try:
        while True:
            remaining_max = max_call - (asyncio.get_event_loop().time() - started)
            if remaining_max <= 0:
                hangup_reason = "timeout"
                should_persist_hangup = True
                await websocket.send_json({"type": "hangup", "reason": hangup_reason})
                break
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=min(idle, remaining_max),
                )
            except asyncio.TimeoutError:
                hangup_reason = "timeout"
                should_persist_hangup = True
                await websocket.send_json({"type": "hangup", "reason": hangup_reason})
                break
            try:
                payload: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "detail": "Invalid JSON.", "code": "VALIDATION"}
                )
                continue
            msg_type = payload.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if msg_type not in _SIGNAL_TYPES:
                await websocket.send_json(
                    {"type": "error", "detail": "Unsupported signal type.", "code": "VALIDATION"}
                )
                continue
            if msg_type == "ice":
                payload = {**payload, "type": "ice-candidate"}
            payload["fromUserId"] = user_id
            if msg_type == "hangup":
                hangup_reason = str(payload.get("reason") or "ended")
                should_persist_hangup = True
                await _broadcast(session_id, websocket, {"type": "hangup", "reason": hangup_reason})
                break
            await _broadcast(session_id, websocket, payload)
    except WebSocketDisconnect:
        hangup_reason = "ended"
        should_persist_hangup = True
    finally:
        async with _rtc_lock:
            room = _rtc_rooms.get(session_id)
            if room and websocket in room:
                room.remove(websocket)
            room_empty = room is not None and len(room) == 0
            if room_empty:
                _rtc_rooms.pop(session_id, None)

        if should_persist_hangup:
            await _broadcast(session_id, websocket, {"type": "hangup", "reason": hangup_reason})
            db = SessionLocal()
            try:
                service = ChatService(db, settings, hub=chat_hub)
                fake_request = _fake_request(settings)
                await service.end_rtc_session(
                    session_id=session_id,
                    ended_by_user_id=user_id,
                    reason=hangup_reason,
                    request=fake_request,
                    insert_call_event=True,
                )
            except Exception:
                pass
            finally:
                db.close()


def _fake_request(settings: Settings) -> StarletteRequest:
    host = "localhost"
    scheme = "http"
    if settings.public_base_url.startswith("https://"):
        scheme = "https"
        host = settings.public_base_url.removeprefix("https://").split("/")[0]
    elif settings.public_base_url.startswith("http://"):
        host = settings.public_base_url.removeprefix("http://").split("/")[0]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": scheme,
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": Headers({"host": host}).raw,
        "client": ("127.0.0.1", 0),
        "server": (host, 443 if scheme == "https" else 80),
    }
    return StarletteRequest(scope)


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
