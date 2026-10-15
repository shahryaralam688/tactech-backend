"""Socket.IO hub for trainer↔trainee chat realtime delivery.

Clients may connect on default `/` or namespace `/chat`. On connect each sid
joins personal room `user:{userId}` so calls ring even when the chat thread is closed.
"""

from __future__ import annotations

from typing import Any

import socketio

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import decode_token
from app.db import models
from app.db.session import SessionLocal

log = get_logger("tactech.chat.sio")

CHAT_NS = "/chat"

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)

# user_id -> set of (namespace, sid)
_user_connections: dict[str, set[tuple[str, str]]] = {}


class ChatHub:
    def is_online(self, user_id: str) -> bool:
        return bool(_user_connections.get(user_id))

    async def emit_message(self, user_id: str, payload: dict[str, Any]) -> None:
        await self._emit_to_user(user_id, "chat.message", payload)

    async def emit_thread_updated(self, user_id: str, payload: dict[str, Any]) -> None:
        await self._emit_to_user(user_id, "chat.thread.updated", payload)

    async def emit_read(self, user_id: str, payload: dict[str, Any]) -> None:
        await self._emit_to_user(user_id, "chat.read", payload)

    async def emit_delivered(self, user_id: str, payload: dict[str, Any]) -> None:
        await self._emit_to_user(user_id, "chat.delivered", payload)

    async def emit_played(self, user_id: str, payload: dict[str, Any]) -> None:
        await self._emit_to_user(user_id, "chat.played", payload)

    async def emit_reaction(self, user_id: str, payload: dict[str, Any]) -> None:
        await self._emit_to_user(user_id, "chat.reaction", payload)

    async def emit_message_deleted(self, user_id: str, payload: dict[str, Any]) -> None:
        await self._emit_to_user(user_id, "chat.message.deleted", payload)

    async def emit_typing(self, user_id: str, payload: dict[str, Any]) -> None:
        await self._emit_to_user(user_id, "chat.typing", payload)

    async def emit_call_incoming(self, user_id: str, payload: dict[str, Any]) -> None:
        log.info(
            "emit_call_incoming",
            user_id=user_id,
            session_id=payload.get("sessionId"),
            online=self.is_online(user_id),
        )
        await self._emit_to_user(user_id, "chat.call.incoming", payload)

    async def emit_call_ended(self, user_id: str, payload: dict[str, Any]) -> None:
        await self._emit_to_user(user_id, "chat.call.ended", payload)

    async def emit_notification(self, user_id: str, payload: dict[str, Any]) -> None:
        await self._emit_to_user(user_id, "notification.created", payload)

    async def emit_relationship_changed(self, user_id: str, payload: dict[str, Any]) -> None:
        """Domain event for roster / My Trainer refresh (room user:{userId}, / + /chat)."""
        await self._emit_to_user(user_id, "relationship.changed", payload)

    async def emit_plan_assignment_changed(self, user_id: str, payload: dict[str, Any]) -> None:
        """Domain event for assigned-plan refresh (room user:{userId}, / + /chat)."""
        await self._emit_to_user(user_id, "plan.assignment.changed", payload)

    async def emit_to_thread(self, thread_id: str, event: str, payload: dict[str, Any]) -> None:
        room = f"chat:{thread_id}"
        for namespace in ("/", CHAT_NS):
            try:
                await sio.emit(event, payload, room=room, namespace=namespace)
            except Exception as exc:
                log.warning("sio_emit_thread_failed", sio_event=event, ns=namespace, error=str(exc)[:160])

    async def _emit_to_user(self, user_id: str, event: str, payload: dict[str, Any]) -> None:
        room = f"user:{user_id}"
        for namespace in ("/", CHAT_NS):
            try:
                await sio.emit(event, payload, room=room, namespace=namespace)
            except Exception as exc:
                log.warning("sio_emit_room_failed", sio_event=event, ns=namespace, error=str(exc)[:160])
        for namespace, sid in list(_user_connections.get(user_id, set())):
            try:
                await sio.emit(event, payload, to=sid, namespace=namespace)
            except Exception as exc:
                log.warning("sio_emit_failed", sio_event=event, ns=namespace, error=str(exc)[:160])


chat_hub = ChatHub()


def _register(sid: str, user_id: str, namespace: str) -> None:
    _user_connections.setdefault(user_id, set()).add((namespace, sid))


def _unregister(sid: str, namespace: str) -> None:
    empty: list[str] = []
    for user_id, conns in _user_connections.items():
        conns.discard((namespace, sid))
        if not conns:
            empty.append(user_id)
    for user_id in empty:
        _user_connections.pop(user_id, None)


async def _authenticate(environ: dict, auth: dict | None) -> str | None:
    token = None
    if isinstance(auth, dict):
        token = auth.get("token") or auth.get("accessToken")
    if not token:
        headers = {
            k.decode().lower() if isinstance(k, bytes) else str(k).lower(): (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in (environ.get("asgi.scope", {}).get("headers") or [])
        }
        auth_header = headers.get("authorization") or environ.get("HTTP_AUTHORIZATION")
        if auth_header and str(auth_header).lower().startswith("bearer "):
            token = str(auth_header).split(" ", 1)[1].strip()
    if not token:
        return None
    settings = get_settings()
    try:
        payload = decode_token(token, settings)
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        db = SessionLocal()
        try:
            user = db.get(models.User, user_id)
            if user is None or user.deleted_at is not None:
                return None
        finally:
            db.close()
        return user_id
    except Exception:
        return None


async def _on_connect(sid: str, environ: dict, auth: dict | None, namespace: str) -> bool:
    user_id = await _authenticate(environ, auth)
    if not user_id:
        log.info("sio_connect_rejected", reason="auth", ns=namespace)
        return False
    _register(sid, user_id, namespace)
    await sio.save_session(sid, {"userId": user_id}, namespace=namespace)
    await sio.enter_room(sid, f"user:{user_id}", namespace=namespace)
    log.info("sio_connected", user_id=user_id, ns=namespace)
    return True


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None) -> bool:
    return await _on_connect(sid, environ, auth, "/")


@sio.event
async def disconnect(sid: str) -> None:
    _unregister(sid, "/")


@sio.on("connect", namespace=CHAT_NS)
async def connect_ns(sid: str, environ: dict, auth: dict | None = None) -> bool:
    return await _on_connect(sid, environ, auth, CHAT_NS)


@sio.on("disconnect", namespace=CHAT_NS)
async def disconnect_ns(sid: str) -> None:
    _unregister(sid, CHAT_NS)


async def _chat_join(sid: str, data: dict | None, namespace: str) -> None:
    try:
        session = await sio.get_session(sid, namespace=namespace)
    except Exception:
        return
    user_id = session.get("userId")
    thread_id = (data or {}).get("threadId")
    if not user_id or not thread_id:
        return
    db = SessionLocal()
    try:
        thread = db.get(models.ChatThread, thread_id)
        if thread is None or user_id not in {thread.trainer_user_id, thread.trainee_user_id}:
            return
    finally:
        db.close()
    await sio.enter_room(sid, f"chat:{thread_id}", namespace=namespace)


async def _chat_leave(sid: str, data: dict | None, namespace: str) -> None:
    thread_id = (data or {}).get("threadId")
    if thread_id:
        await sio.leave_room(sid, f"chat:{thread_id}", namespace=namespace)


async def _chat_typing(sid: str, data: dict | None, namespace: str) -> None:
    try:
        session = await sio.get_session(sid, namespace=namespace)
    except Exception:
        return
    user_id = session.get("userId")
    data = data or {}
    thread_id = data.get("threadId")
    if not user_id or not thread_id:
        return
    payload = {
        "threadId": thread_id,
        "userId": user_id,
        "isTyping": bool(data.get("isTyping", True)),
    }
    await sio.emit(
        "chat.typing",
        payload,
        room=f"chat:{thread_id}",
        skip_sid=sid,
        namespace=namespace,
    )


def _socket_principal(user_id: str):
    from app.api.deps import Principal

    db = SessionLocal()
    try:
        user = db.get(models.User, user_id)
        if user is None:
            db.close()
            return None, None
        trainer_id = user.trainer.id if user.trainer else None
        trainee_id = user.trainee.id if user.trainee else None
        return (
            Principal(
                user_id=user.id,
                role=user.role,
                trainer_id=trainer_id,
                trainee_id=trainee_id,
            ),
            db,
        )
    except Exception:
        db.close()
        return None, None


async def _chat_delivered(sid: str, data: dict | None, namespace: str) -> None:
    try:
        session = await sio.get_session(sid, namespace=namespace)
    except Exception:
        return
    user_id = session.get("userId")
    data = data or {}
    thread_id = data.get("threadId")
    up_to = data.get("upToMessageId")
    if not user_id or not thread_id or not up_to:
        return
    from app.core.config import get_settings
    from app.services.chat_service import ChatService

    principal, db = _socket_principal(user_id)
    if principal is None or db is None:
        return
    try:
        service = ChatService(db, get_settings(), hub=chat_hub)
        await service.mark_delivered(principal, thread_id, up_to)
    except Exception as exc:
        log.warning("chat_delivered_failed", error=str(exc)[:160])
    finally:
        db.close()


async def _chat_played(sid: str, data: dict | None, namespace: str) -> None:
    try:
        session = await sio.get_session(sid, namespace=namespace)
    except Exception:
        return
    user_id = session.get("userId")
    data = data or {}
    thread_id = data.get("threadId")
    message_id = data.get("messageId")
    if not user_id or not thread_id or not message_id:
        return
    from app.core.config import get_settings
    from app.services.chat_service import ChatService

    principal, db = _socket_principal(user_id)
    if principal is None or db is None:
        return
    try:
        service = ChatService(db, get_settings(), hub=chat_hub)
        await service.mark_played(principal, thread_id, message_id)
    except Exception as exc:
        log.warning("chat_played_failed", error=str(exc)[:160])
    finally:
        db.close()


async def _chat_react(sid: str, data: dict | None, namespace: str) -> None:
    try:
        session = await sio.get_session(sid, namespace=namespace)
    except Exception:
        return
    user_id = session.get("userId")
    data = data or {}
    thread_id = data.get("threadId")
    message_id = data.get("messageId")
    emoji = data.get("emoji")
    if not user_id or not thread_id or not message_id or not emoji:
        return
    from app.core.config import get_settings
    from app.services.chat_service import ChatService

    principal, db = _socket_principal(user_id)
    if principal is None or db is None:
        return
    try:
        service = ChatService(db, get_settings(), hub=chat_hub)
        await service.react(principal, thread_id, message_id, emoji)
    except Exception as exc:
        log.warning("chat_react_failed", error=str(exc)[:160])
    finally:
        db.close()


async def _chat_unreact(sid: str, data: dict | None, namespace: str) -> None:
    try:
        session = await sio.get_session(sid, namespace=namespace)
    except Exception:
        return
    user_id = session.get("userId")
    data = data or {}
    thread_id = data.get("threadId")
    message_id = data.get("messageId")
    emoji = data.get("emoji")
    if not user_id or not thread_id or not message_id or not emoji:
        return
    from app.core.config import get_settings
    from app.services.chat_service import ChatService

    principal, db = _socket_principal(user_id)
    if principal is None or db is None:
        return
    try:
        service = ChatService(db, get_settings(), hub=chat_hub)
        await service.unreact(principal, thread_id, message_id, emoji)
    except Exception as exc:
        log.warning("chat_unreact_failed", error=str(exc)[:160])
    finally:
        db.close()


@sio.on("chat.join")
async def chat_join(sid: str, data: dict | None = None) -> None:
    await _chat_join(sid, data, "/")


@sio.on("chat.leave")
async def chat_leave(sid: str, data: dict | None = None) -> None:
    await _chat_leave(sid, data, "/")


@sio.on("chat.typing")
async def chat_typing(sid: str, data: dict | None = None) -> None:
    await _chat_typing(sid, data, "/")


@sio.on("chat.delivered")
async def chat_delivered(sid: str, data: dict | None = None) -> None:
    await _chat_delivered(sid, data, "/")


@sio.on("chat.played")
async def chat_played(sid: str, data: dict | None = None) -> None:
    await _chat_played(sid, data, "/")


@sio.on("chat.react")
async def chat_react(sid: str, data: dict | None = None) -> None:
    await _chat_react(sid, data, "/")


@sio.on("chat.unreact")
async def chat_unreact(sid: str, data: dict | None = None) -> None:
    await _chat_unreact(sid, data, "/")


@sio.on("chat.join", namespace=CHAT_NS)
async def chat_join_ns(sid: str, data: dict | None = None) -> None:
    await _chat_join(sid, data, CHAT_NS)


@sio.on("chat.leave", namespace=CHAT_NS)
async def chat_leave_ns(sid: str, data: dict | None = None) -> None:
    await _chat_leave(sid, data, CHAT_NS)


@sio.on("chat.typing", namespace=CHAT_NS)
async def chat_typing_ns(sid: str, data: dict | None = None) -> None:
    await _chat_typing(sid, data, CHAT_NS)


@sio.on("chat.delivered", namespace=CHAT_NS)
async def chat_delivered_ns(sid: str, data: dict | None = None) -> None:
    await _chat_delivered(sid, data, CHAT_NS)


@sio.on("chat.played", namespace=CHAT_NS)
async def chat_played_ns(sid: str, data: dict | None = None) -> None:
    await _chat_played(sid, data, CHAT_NS)


@sio.on("chat.react", namespace=CHAT_NS)
async def chat_react_ns(sid: str, data: dict | None = None) -> None:
    await _chat_react(sid, data, CHAT_NS)


@sio.on("chat.unreact", namespace=CHAT_NS)
async def chat_unreact_ns(sid: str, data: dict | None = None) -> None:
    await _chat_unreact(sid, data, CHAT_NS)
