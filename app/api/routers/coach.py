from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse

from app.ai.capabilities import AiCapabilitiesOut, build_capabilities
from app.ai.gateway import AiGateway
from app.api.deps import (
    Principal,
    enforce_coach_chat_rate_limit,
    enforce_coach_image_rate_limit,
    enforce_coach_rtc_rate_limit,
    enforce_coach_voice_rate_limit,
    get_ai_program_service,
    get_coach_service,
    get_principal,
    get_settings,
    require_ai_access,
    require_trainee,
)
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
from app.schemas.common import APIModel, WorkoutPlanOut
from app.services.ai_program_service import AiProgramService
from app.services.coach_service import CoachService

router = APIRouter(prefix="/coach", tags=["ai-coach"])


class GenerateProgramRequest(APIModel):
    horizon_days: int = 7
    notes: str | None = None


class WeeklySummaryOut(APIModel):
    summary: str
    log_count: int = 0

# In-memory WebRTC signaling rooms (single-process). Use Redis pub/sub for multi-worker later.
_rtc_rooms: dict[str, set[WebSocket]] = {}
_rtc_lock = asyncio.Lock()
_RTC_IDLE_SECONDS = 300


@router.get("/status", response_model=CoachProviderStatusOut)
def coach_status(service: Annotated[CoachService, Depends(get_coach_service)]) -> CoachProviderStatusOut:
    return service.status()


@router.get("/ai/capabilities", response_model=AiCapabilitiesOut)
def ai_capabilities(
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AiCapabilitiesOut:
    """Authenticated capability map so clients know what AI is live vs stub."""
    _ = principal
    return build_capabilities(settings)


@router.post("/programs/generate", response_model=WorkoutPlanOut)
async def generate_program(
    payload: GenerateProgramRequest,
    principal: Annotated[Principal, Depends(require_trainee)],
    service: Annotated[AiProgramService, Depends(get_ai_program_service)],
) -> WorkoutPlanOut:
    """Solo trainee structured plan (blocked with 409 HAS_TRAINER if linked)."""
    return await service.generate(
        principal,
        horizon_days=payload.horizon_days,
        notes=payload.notes,
    )


@router.post("/programs/weekly-summary", response_model=WeeklySummaryOut)
async def weekly_summary(
    principal: Annotated[Principal, Depends(require_ai_access)],
    service: Annotated[AiProgramService, Depends(get_ai_program_service)],
) -> WeeklySummaryOut:
    """Free: uses same chat quota as /coach/chat. Advanced/Pro: unlimited via entitlement."""
    raw = await service.weekly_summary(principal)
    return WeeklySummaryOut(summary=raw["summary"], log_count=raw["logCount"])


@router.post("/vision/pose")
async def vision_pose(
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
    image: UploadFile = File(...),
    prompt: str | None = Form(default=None),
):
    """Pose AI — stub until paid vision keys exist (501 AI_CAPABILITY_UNAVAILABLE)."""
    _ = principal
    data = await image.read()
    gateway = AiGateway(settings)
    return await gateway.pose.analyze(
        image_bytes=data,
        content_type=image.content_type,
        prompt=prompt or "",
    )


@router.post("/vision/food")
async def vision_food(
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
    image: UploadFile = File(...),
    prompt: str | None = Form(default=None),
):
    """Food scan AI — stub until paid vision keys exist (501 AI_CAPABILITY_UNAVAILABLE)."""
    _ = principal
    data = await image.read()
    gateway = AiGateway(settings)
    return await gateway.food.analyze(
        image_bytes=data,
        content_type=image.content_type,
        prompt=prompt or "",
    )


@router.post("/memory/sync", response_model=CoachMemorySyncOut)
async def sync_memory(
    principal: Annotated[Principal, Depends(require_ai_access)],
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


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_conversation(
    conversation_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[CoachService, Depends(get_coach_service)],
) -> Response:
    """Delete an AI Coach conversation owned by the current user (cascade messages + media GC)."""
    closed_sessions = service.delete_conversation(principal, conversation_id)
    for session_id in closed_sessions:
        await _hangup_rtc_room(session_id, reason="conversation_deleted")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    principal: Annotated[Principal, Depends(require_ai_access)],
    service: Annotated[CoachService, Depends(get_coach_service)],
    _: Annotated[None, Depends(enforce_coach_chat_rate_limit)] = None,
):
    if payload.stream:

        async def event_gen():
            try:
                async for chunk in service.stream_chat(
                    principal, payload.message, payload.conversation_id, request
                ):
                    yield f"data: {chunk}\n\n"
            except AppError as exc:
                payload_err = {
                    "event": "error",
                    "detail": exc.message,
                    "code": exc.code or "INTERNAL",
                    "statusCode": exc.status_code,
                }
                yield f"data: {json.dumps(payload_err)}\n\n"
            except Exception:
                payload_err = {
                    "event": "error",
                    "detail": "AI coach failed unexpectedly. Try again.",
                    "code": "INTERNAL",
                    "statusCode": 500,
                }
                yield f"data: {json.dumps(payload_err)}\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream")
    return await service.chat(principal, payload.message, payload.conversation_id, request)


@router.post("/chat/image", response_model=CoachImageChatResponse, status_code=status.HTTP_201_CREATED)
async def chat_with_image(
    request: Request,
    principal: Annotated[Principal, Depends(require_ai_access)],
    service: Annotated[CoachService, Depends(get_coach_service)],
    _: Annotated[None, Depends(enforce_coach_image_rate_limit)] = None,
    image: UploadFile = File(...),
    message: str | None = Form(default=None),
    # iOS multipart uses snake_case; also accept camelCase.
    conversation_id: str | None = Form(default=None),
    conversationId: str | None = Form(default=None),
) -> CoachImageChatResponse:
    """Share a JPEG/PNG photo for AI coaching analysis (form, meal, progress, etc.)."""
    return await service.chat_with_image(
        principal, image, message, conversation_id or conversationId, request
    )


@router.post("/voice/turn", response_model=CoachVoiceTurnOut)
async def voice_turn(
    request: Request,
    principal: Annotated[Principal, Depends(require_ai_access)],
    service: Annotated[CoachService, Depends(get_coach_service)],
    _: Annotated[None, Depends(enforce_coach_voice_rate_limit)] = None,
    audio: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
    conversationId: str | None = Form(default=None),
    speak: bool = Form(default=True),
) -> CoachVoiceTurnOut:
    return await service.voice_turn(
        principal, audio, conversation_id or conversationId, request, speak=speak
    )


@router.get("/rtc/ice-servers", response_model=list[CoachRtcIceServer])
def ice_servers(service: Annotated[CoachService, Depends(get_coach_service)]) -> list[CoachRtcIceServer]:
    return service.ice_servers()


@router.post("/rtc/sessions", response_model=CoachRtcSessionOut, status_code=status.HTTP_201_CREATED)
def create_rtc_session(
    request: Request,
    principal: Annotated[Principal, Depends(require_ai_access)],
    service: Annotated[CoachService, Depends(get_coach_service)],
    _: Annotated[None, Depends(enforce_coach_rtc_rate_limit)] = None,
    # iOS uses conversationId; also accept snake_case.
    conversationId: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
) -> CoachRtcSessionOut:
    return service.create_rtc_session(principal, conversationId or conversation_id, request)


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
    """WebRTC signaling: joined / offer / answer / ice / voice_hint / hangup / ping→pong."""
    settings = get_settings()
    await websocket.accept()
    user_id = await _ws_user_id(websocket, settings, token)
    if user_id is None:
        await websocket.send_json({"type": "error", "detail": "Authentication required.", "code": "UNAUTHORIZED"})
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        # Creating the RTC session is AI-gated; signaling requires an open owned session.
        repo = CoachRepository(db)
        session = repo.get_rtc_session(session_id, user_id)
        if session is None or session.status != "open":
            await websocket.send_json(
                {"type": "error", "detail": "RTC session not found.", "code": "NOT_FOUND"}
            )
            await websocket.close(code=4404)
            return
        access = AiAccessService(db, settings)
        if not access.is_entitlement_active(user_id) and access.free_tease_limit() == 0:
            await websocket.send_json(
                {
                    "type": "error",
                    "detail": "AI Coach Pro is required to continue.",
                    "code": "AI_REQUIRED",
                }
            )
            await websocket.close(code=4402)
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

    hangup_reason = "user"
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=_RTC_IDLE_SECONDS)
            except asyncio.TimeoutError:
                hangup_reason = "timeout"
                await websocket.send_json({"type": "hangup", "reason": hangup_reason})
                break
            try:
                payload: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "Invalid JSON.", "code": "VALIDATION_ERROR"})
                continue
            msg_type = payload.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if msg_type not in {"offer", "answer", "ice", "hangup", "voice_hint"}:
                await websocket.send_json(
                    {"type": "error", "detail": "Unsupported signal type.", "code": "VALIDATION_ERROR"}
                )
                continue
            payload["fromUserId"] = user_id
            if msg_type == "hangup":
                hangup_reason = str(payload.get("reason") or "user")
                await _broadcast(session_id, websocket, {"type": "hangup", "reason": hangup_reason})
                break
            await _broadcast(session_id, websocket, payload)
    except WebSocketDisconnect:
        hangup_reason = "error"
    finally:
        _close_rtc_session(session_id, user_id)
        async with _rtc_lock:
            room = _rtc_rooms.get(session_id)
            if room and websocket in room:
                room.remove(websocket)
            if room is not None and not room:
                _rtc_rooms.pop(session_id, None)


def _close_rtc_session(session_id: str, user_id: str) -> None:
    db = SessionLocal()
    try:
        repo = CoachRepository(db)
        session = repo.get_rtc_session(session_id, user_id)
        if session is not None and session.status == "open":
            repo.close_rtc_session(session)
    except Exception:
        pass
    finally:
        db.close()


async def _hangup_rtc_room(session_id: str, *, reason: str = "user") -> None:
    """Notify signaling peers and drop the in-memory room."""
    payload = {"type": "hangup", "reason": reason, "sessionId": session_id}
    async with _rtc_lock:
        peers = list(_rtc_rooms.get(session_id, set()))
        _rtc_rooms.pop(session_id, None)
    for peer in peers:
        try:
            await peer.send_json(payload)
            await peer.close()
        except Exception:
            pass


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
