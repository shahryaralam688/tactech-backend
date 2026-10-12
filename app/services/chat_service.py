from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import Request, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationAppError
from app.core.storage import absolute_media_url, ensure_upload_dir, public_base, read_chat_attachment, save_bytes
from app.db import models
from app.repositories.chat import ChatRepository, build_preview, reply_preview
from app.schemas.chat import (
    ChatDeliveredOut,
    ChatIceServer,
    ChatIceServersOut,
    ChatIncomingCallOut,
    ChatIncomingCallsOut,
    ChatMessageOut,
    ChatMessagePage,
    ChatPlayedOut,
    ChatReactionEventOut,
    ChatReactionOut,
    ChatReadOut,
    ChatRtcSessionOut,
    ChatThreadOut,
    ChatThreadPage,
)
from app.services.push_service import PushService

if TYPE_CHECKING:
    from app.api.deps import Principal
    from app.realtime.chat_hub import ChatHub


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _format_call_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"Call · {minutes:02d}:{secs:02d}"


class ChatService:
    def __init__(self, db: Session, settings: Settings, hub: ChatHub | None = None) -> None:
        self.db = db
        self.settings = settings
        self.repo = ChatRepository(db)
        self.push = PushService(db, hub=hub)
        self.hub = hub

    def list_threads(self, principal: Principal, request: Request) -> ChatThreadPage:
        threads = self.repo.list_threads_for_user(principal.user_id)
        # Inbox shows threads after first message (spec preference).
        threads = [t for t in threads if t.last_message_at is not None]
        items = [self._thread_out(t, principal, request) for t in threads]
        return ChatThreadPage(items=items, next_cursor=None)

    def find_or_create_thread(
        self,
        principal: Principal,
        request: Request,
        *,
        peer_user_id: str | None = None,
        peer_trainee_profile_id: str | None = None,
        peer_trainer_profile_id: str | None = None,
    ) -> tuple[ChatThreadOut, bool]:
        if not any([peer_user_id, peer_trainee_profile_id, peer_trainer_profile_id]):
            raise ValidationAppError(
                "Provide peerUserId (preferred), peerTraineeProfileId, or peerTrainerProfileId."
            )
        resolved_peer = self._resolve_peer_user_id(
            peer_user_id=peer_user_id,
            peer_trainee_profile_id=peer_trainee_profile_id,
            peer_trainer_profile_id=peer_trainer_profile_id,
        )
        trainer_user_id, trainee_user_id = self._resolve_pair(principal, resolved_peer)
        existing = self.repo.find_thread(trainer_user_id, trainee_user_id)
        created = False
        if existing is None:
            existing = self.repo.create_thread(trainer_user_id, trainee_user_id)
            created = True
        return self._thread_out(existing, principal, request), created

    def list_messages(
        self,
        principal: Principal,
        thread_id: str,
        request: Request,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> ChatMessagePage:
        thread = self._owned_thread(principal, thread_id)
        limit = max(1, min(limit, 100))
        rows = self.repo.list_messages(thread.id, limit=limit + 1, before_id=cursor)
        next_cursor = None
        if len(rows) > limit:
            oldest = rows[0]
            rows = rows[1:]
            next_cursor = oldest.id
        return ChatMessagePage(
            items=[self._message_out(m, request) for m in rows],
            next_cursor=next_cursor,
        )

    async def send_message(
        self,
        principal: Principal,
        thread_id: str,
        request: Request,
        *,
        text: str | None,
        client_id: str | None,
        file: UploadFile | None = None,
        kind: str | None = None,
        call_outcome: str | None = None,
        duration_seconds: int | None = None,
        attachment_type_hint: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> ChatMessageOut:
        thread = self._owned_thread(principal, thread_id)
        cleaned = (text or "").strip() or None
        if cleaned and len(cleaned) > self.settings.chat_message_max_chars:
            raise ValidationAppError(
                f"Message must be at most {self.settings.chat_message_max_chars} characters.",
                fields={"text": "too_long"},
            )

        if client_id:
            existing = self.repo.get_message_by_client_id(
                thread.id, client_id, sender_user_id=principal.user_id
            )
            if existing is not None:
                return self._message_out(existing, request)

        reply_id, reply_text, reply_name = self._resolve_reply(thread.id, reply_to_message_id)

        message_kind = (kind or "").strip() or None
        attachment_url = None
        attachment_type = None
        if file is not None and file.filename:
            raw, extension, attachment_type = await read_chat_attachment(
                file, self.settings, attachment_type_hint=attachment_type_hint
            )
            ensure_upload_dir(self.settings)
            attachment_url = save_bytes(self.settings, "chat", raw, extension)
            message_kind = message_kind or "attachment"

        if message_kind == "call_event":
            outcome = (call_outcome or "").strip() or "📞 Call"
            message = self.repo.add_message(
                thread,
                sender_user_id=principal.user_id,
                sender_role=principal.role,
                kind="call_event",
                text=cleaned,
                call_outcome=outcome[:120],
                duration_seconds=duration_seconds,
                client_id=client_id,
                reply_to_message_id=reply_id,
                reply_to_text=reply_text,
                reply_to_sender_name=reply_name,
            )
        else:
            if not cleaned and not attachment_url:
                raise ValidationAppError(
                    "Message text or attachment is required.",
                    fields={"text": "required"},
                )
            message = self.repo.add_message(
                thread,
                sender_user_id=principal.user_id,
                sender_role=principal.role,
                kind=message_kind or ("attachment" if attachment_url else "text"),
                text=cleaned,
                attachment_url=attachment_url,
                attachment_type=attachment_type,
                duration_seconds=duration_seconds,
                client_id=client_id,
                reply_to_message_id=reply_id,
                reply_to_text=reply_text,
                reply_to_sender_name=reply_name,
            )

        return await self._after_message(principal, thread, message, request)

    async def mark_delivered(
        self, principal: Principal, thread_id: str, up_to_message_id: str
    ) -> ChatDeliveredOut:
        thread = self._owned_thread(principal, thread_id)
        _, delivered_at = self.repo.mark_delivered(
            thread, delivered_by_user_id=principal.user_id, up_to_message_id=up_to_message_id
        )
        at = delivered_at or _utcnow()
        payload = ChatDeliveredOut(
            thread_id=thread.id,
            up_to_message_id=up_to_message_id,
            delivered_by_user_id=principal.user_id,
            delivered_at=at,
        )
        peer_id = self._peer_user_id(thread, principal.user_id)
        if self.hub is not None:
            data = payload.model_dump(by_alias=True, mode="json")
            await self.hub.emit_delivered(peer_id, data)
            await self.hub.emit_to_thread(thread.id, "chat.delivered", data)
        return payload

    async def mark_read(
        self, principal: Principal, thread_id: str, up_to_message_id: str
    ) -> ChatReadOut:
        thread = self._owned_thread(principal, thread_id)
        self.repo.mark_read(thread, reader_user_id=principal.user_id, up_to_message_id=up_to_message_id)
        unread = (
            thread.trainer_unread_count
            if principal.user_id == thread.trainer_user_id
            else thread.trainee_unread_count
        )
        payload = ChatReadOut(
            thread_id=thread.id,
            up_to_message_id=up_to_message_id,
            reader_user_id=principal.user_id,
            unread_count=int(unread or 0),
        )
        peer_id = self._peer_user_id(thread, principal.user_id)
        if self.hub is not None:
            data = payload.model_dump(by_alias=True, mode="json")
            await self.hub.emit_read(peer_id, data)
            await self.hub.emit_to_thread(thread.id, "chat.read", data)
        return payload

    async def mark_played(
        self, principal: Principal, thread_id: str, message_id: str
    ) -> ChatPlayedOut:
        thread = self._owned_thread(principal, thread_id)
        message = self.repo.get_message(message_id)
        if message is None or message.thread_id != thread.id:
            raise NotFoundError("Message not found.")
        if message.sender_user_id == principal.user_id:
            raise ForbiddenError("You cannot mark your own voice note as played.")
        if message.attachment_type != "voice" and message.kind != "voice":
            raise ValidationAppError("Only voice messages can be marked played.")
        if message.deleted_for_everyone_at is not None:
            raise ValidationAppError("Message was deleted.")
        played_at = self.repo.mark_played(message, played_by_user_id=principal.user_id)
        assert played_at is not None
        payload = ChatPlayedOut(
            thread_id=thread.id,
            message_id=message.id,
            played_by_user_id=principal.user_id,
            played_at=played_at,
        )
        if self.hub is not None:
            data = payload.model_dump(by_alias=True, mode="json")
            await self.hub.emit_played(message.sender_user_id, data)
            await self.hub.emit_to_thread(thread.id, "chat.played", data)
        return payload

    async def react(
        self, principal: Principal, thread_id: str, message_id: str, emoji: str
    ) -> ChatReactionEventOut:
        thread = self._owned_thread(principal, thread_id)
        message = self.repo.get_message(message_id)
        if message is None or message.thread_id != thread.id:
            raise NotFoundError("Message not found.")
        if message.deleted_for_everyone_at is not None:
            raise ValidationAppError("Cannot react to a deleted message.")
        cleaned = (emoji or "").strip()
        if not cleaned or len(cleaned) > 32:
            raise ValidationAppError("Invalid emoji.", fields={"emoji": "invalid"})
        self.repo.upsert_reaction(message, user_id=principal.user_id, emoji=cleaned)
        return await self._emit_reactions(thread, message)

    async def unreact(
        self, principal: Principal, thread_id: str, message_id: str, emoji: str
    ) -> ChatReactionEventOut:
        thread = self._owned_thread(principal, thread_id)
        message = self.repo.get_message(message_id)
        if message is None or message.thread_id != thread.id:
            raise NotFoundError("Message not found.")
        cleaned = (emoji or "").strip()
        self.repo.remove_reaction(message, user_id=principal.user_id, emoji=cleaned)
        return await self._emit_reactions(thread, message)

    async def edit_message(
        self, principal: Principal, thread_id: str, message_id: str, text: str, request: Request
    ) -> ChatMessageOut:
        thread = self._owned_thread(principal, thread_id)
        message = self.repo.get_message(message_id)
        if message is None or message.thread_id != thread.id:
            raise NotFoundError("Message not found.")
        if message.sender_user_id != principal.user_id:
            raise ForbiddenError("Only the sender can edit this message.")
        if message.deleted_for_everyone_at is not None:
            raise ValidationAppError("Cannot edit a deleted message.")
        if (message.kind or "text") != "text" or message.attachment_url:
            raise ValidationAppError("Only text messages can be edited.")
        age = (_utcnow() - _aware(message.created_at)).total_seconds()
        if age > self.settings.chat_edit_window_seconds:
            raise ForbiddenError("Edit window has expired (15 minutes).")
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValidationAppError("Message text is required.", fields={"text": "required"})
        if len(cleaned) > self.settings.chat_message_max_chars:
            raise ValidationAppError(
                f"Message must be at most {self.settings.chat_message_max_chars} characters.",
                fields={"text": "too_long"},
            )
        message = self.repo.edit_text(message, cleaned)
        if thread.last_message_at == message.created_at or (
            thread.last_message_preview and message.id
        ):
            # Refresh preview if this was still the latest-ish text; best-effort.
            latest = self.repo.list_messages(thread.id, limit=1)
            if latest and latest[-1].id == message.id:
                thread.last_message_preview = cleaned[:280]
                thread.updated_at = _utcnow()
                self.db.commit()
                self.db.refresh(thread)
        out = self._message_out(message, request)
        if self.hub is not None:
            data = out.model_dump(by_alias=True, mode="json")
            peer_id = self._peer_user_id(thread, principal.user_id)
            await self.hub.emit_message(peer_id, data)
            await self.hub.emit_message(principal.user_id, data)
            await self.hub.emit_to_thread(thread.id, "chat.message", data)
        return out

    async def delete_message(
        self,
        principal: Principal,
        thread_id: str,
        message_id: str,
        *,
        scope: str,
        request: Request,
    ) -> ChatMessageOut | None:
        thread = self._owned_thread(principal, thread_id)
        message = self.repo.get_message(message_id)
        if message is None or message.thread_id != thread.id:
            raise NotFoundError("Message not found.")
        scope_n = (scope or "everyone").strip().lower()
        if scope_n == "me":
            # Server-side hide-for-me is not persisted yet; client-local is OK.
            return None
        if scope_n != "everyone":
            raise ValidationAppError("scope must be everyone or me.", fields={"scope": "invalid"})
        if message.sender_user_id != principal.user_id:
            raise ForbiddenError("Only the sender can delete for everyone.")
        if message.deleted_for_everyone_at is not None:
            return self._message_out(message, request)
        age = (_utcnow() - _aware(message.created_at)).total_seconds()
        if age > self.settings.chat_delete_everyone_seconds:
            raise ForbiddenError("Delete-for-everyone window has expired (1 hour).")
        message = self.repo.soft_delete_everyone(message)
        out = self._message_out(message, request)
        if self.hub is not None:
            deleted = {
                "threadId": thread.id,
                "messageId": message.id,
                "scope": "everyone",
            }
            peer_id = self._peer_user_id(thread, principal.user_id)
            await self.hub.emit_message_deleted(peer_id, deleted)
            await self.hub.emit_message_deleted(principal.user_id, deleted)
            await self.hub.emit_to_thread(thread.id, "chat.message.deleted", deleted)
            data = out.model_dump(by_alias=True, mode="json")
            await self.hub.emit_message(peer_id, data)
            await self.hub.emit_to_thread(thread.id, "chat.message", data)
        return out

    async def _emit_reactions(
        self, thread: models.ChatThread, message: models.ChatMessage
    ) -> ChatReactionEventOut:
        reactions = [
            ChatReactionOut(emoji=r.emoji, user_id=r.user_id, created_at=r.created_at)
            for r in self.repo.list_reactions(message.id)
        ]
        payload = ChatReactionEventOut(
            thread_id=thread.id,
            message_id=message.id,
            reactions=reactions,
        )
        if self.hub is not None:
            data = payload.model_dump(by_alias=True, mode="json")
            await self.hub.emit_reaction(thread.trainer_user_id, data)
            await self.hub.emit_reaction(thread.trainee_user_id, data)
            await self.hub.emit_to_thread(thread.id, "chat.reaction", data)
        return payload

    def _resolve_reply(
        self, thread_id: str, reply_to_message_id: str | None
    ) -> tuple[str | None, str | None, str | None]:
        if not reply_to_message_id:
            return None, None, None
        original = self.repo.get_message(reply_to_message_id)
        if original is None or original.thread_id != thread_id:
            raise ValidationAppError(
                "replyToMessageId must belong to this thread.",
                fields={"replyToMessageId": "invalid"},
            )
        deleted = original.deleted_for_everyone_at is not None
        preview = reply_preview(
            kind=original.kind or "text",
            text=original.text,
            attachment_type=original.attachment_type,
            call_outcome=original.call_outcome,
            deleted=deleted,
        )
        sender = self.db.get(models.User, original.sender_user_id)
        name = (sender.name if sender else None) or "User"
        return original.id, preview, name[:120]

    def ice_servers(self) -> ChatIceServersOut:
        return ChatIceServersOut(ice_servers=self._ice_server_list())

    async def create_rtc_session(
        self, principal: Principal, thread_id: str, request: Request
    ) -> ChatRtcSessionOut:
        thread = self._owned_thread(principal, thread_id)
        # End any prior active session on this thread.
        for prior in self.repo.list_active_rtc_for_thread(thread.id):
            self.repo.end_rtc_session(prior)
            if self.hub is not None:
                for uid in {thread.trainer_user_id, thread.trainee_user_id}:
                    await self.hub.emit_call_ended(
                        uid,
                        {
                            "threadId": thread.id,
                            "sessionId": prior.id,
                            "reason": "ended",
                        },
                    )

        session = self.repo.create_rtc_session(thread.id, principal.user_id)
        out = self._rtc_out(session, request)
        peer_id = self._peer_user_id(thread, principal.user_id)
        sender = self.db.get(models.User, principal.user_id)
        from_name = sender.name if sender else "Incoming call"
        incoming = {
            "threadId": thread.id,
            "sessionId": session.id,
            "fromUserId": principal.user_id,
            "fromName": from_name,
            "signalingPath": out.signaling_path,
        }
        # Always emit to peer's personal Socket room (Home tab / any screen).
        if self.hub is not None:
            await self.hub.emit_call_incoming(peer_id, incoming)

        await self.push.notify_chat_call(
            recipient_user_id=peer_id,
            title=from_name,
            body="Incoming video call",
            thread_id=thread.id,
            session_id=session.id,
            from_user_id=principal.user_id,
            from_name=from_name,
            signaling_path=out.signaling_path,
            high_priority=True,
            skip_if_online=True,
        )
        return out

    def list_incoming_calls(
        self, principal: Principal, request: Request
    ) -> ChatIncomingCallsOut:
        rows = self.repo.list_incoming_rtc_for_user(principal.user_id)
        items: list[ChatIncomingCallOut] = []
        for session in rows:
            thread = self.repo.get_thread(session.thread_id)
            if thread is None:
                continue
            if principal.user_id not in {thread.trainer_user_id, thread.trainee_user_id}:
                continue
            caller = self.db.get(models.User, session.created_by_user_id)
            rtc = self._rtc_out(session, request)
            items.append(
                ChatIncomingCallOut(
                    thread_id=session.thread_id,
                    session_id=session.id,
                    from_user_id=session.created_by_user_id,
                    from_name=caller.name if caller else "Incoming call",
                    signaling_path=rtc.signaling_path,
                    created_at=session.created_at,
                )
            )
        return ChatIncomingCallsOut(items=items)

    def get_rtc_session(
        self, principal: Principal, session_id: str, request: Request
    ) -> ChatRtcSessionOut:
        session = self.repo.get_rtc_session(session_id)
        if session is None:
            raise NotFoundError("Call session not found.")
        self._owned_thread(principal, session.thread_id)
        return self._rtc_out(session, request)

    async def end_rtc_session(
        self,
        *,
        session_id: str,
        ended_by_user_id: str,
        reason: str = "ended",
        request: Request | None = None,
        insert_call_event: bool = True,
    ) -> models.ChatRtcSession | None:
        session = self.repo.get_rtc_session(session_id)
        if session is None or session.status != "active":
            return session
        thread = self.repo.get_thread(session.thread_id)
        if thread is None:
            return None
        ended = self.repo.end_rtc_session(session)
        duration = 0
        if ended.created_at:
            duration = int((_utcnow() - ended.created_at).total_seconds())

        if insert_call_event:
            outcome = {
                "declined": "Cancelled call",
                "failed": "Call failed",
                "timeout": "Missed call",
            }.get(reason)
            if outcome is None:
                outcome = _format_call_duration(duration) if duration >= 1 else "📞 Call"
            role = "trainer" if ended_by_user_id == thread.trainer_user_id else "trainee"
            message = self.repo.add_message(
                thread,
                sender_user_id=ended_by_user_id,
                sender_role=role,
                kind="call_event",
                call_outcome=outcome,
                duration_seconds=duration or None,
                bump_unread=True,
            )
            if request is not None:
                # Fan-out call event as a normal message
                dummy = _PeerPrincipal(ended_by_user_id)
                dummy.role = role
                await self._after_message(dummy, thread, message, request)  # type: ignore[arg-type]

        if self.hub is not None:
            payload = {"threadId": thread.id, "sessionId": session_id, "reason": reason}
            for uid in {thread.trainer_user_id, thread.trainee_user_id}:
                await self.hub.emit_call_ended(uid, payload)
        return ended

    def _resolve_peer_user_id(
        self,
        *,
        peer_user_id: str | None,
        peer_trainee_profile_id: str | None,
        peer_trainer_profile_id: str | None,
    ) -> str:
        if peer_trainee_profile_id:
            trainee = self.db.get(models.TraineeProfile, peer_trainee_profile_id)
            if trainee is None:
                raise NotFoundError("Trainee not found.")
            return trainee.user_id
        if peer_trainer_profile_id:
            trainer = self.db.get(models.TrainerProfile, peer_trainer_profile_id)
            if trainer is None:
                raise NotFoundError("Trainer not found.")
            return trainer.user_id
        if not peer_user_id:
            raise ValidationAppError("Provide peerUserId.")

        user = self.db.get(models.User, peer_user_id)
        if user is not None and user.deleted_at is None:
            return peer_user_id

        # iOS roster often holds TraineeProfile.id — resolve if peerUserId was a profile id.
        trainee = self.db.get(models.TraineeProfile, peer_user_id)
        if trainee is not None:
            return trainee.user_id
        trainer = self.db.get(models.TrainerProfile, peer_user_id)
        if trainer is not None:
            return trainer.user_id
        raise NotFoundError("User not found.")

    def _resolve_pair(self, principal: Principal, peer_user_id: str) -> tuple[str, str]:
        peer = self.db.get(models.User, peer_user_id)
        if peer is None or peer.deleted_at is not None:
            raise NotFoundError("User not found.")

        if principal.role == "trainer":
            if not principal.trainer_id:
                raise ForbiddenError("Trainer access required.")
            trainee = (
                self.db.query(models.TraineeProfile)
                .options(joinedload(models.TraineeProfile.user))
                .filter(models.TraineeProfile.user_id == peer_user_id)
                .one_or_none()
            )
            if trainee is None or trainee.trainer_id != principal.trainer_id:
                raise ForbiddenError("This trainee is not on your roster.")
            return principal.user_id, peer_user_id

        if principal.role == "trainee":
            if not principal.trainee_id:
                raise ForbiddenError("Trainee access required.")
            me = self.db.get(models.TraineeProfile, principal.trainee_id)
            if me is None or me.trainer_id is None:
                raise ForbiddenError("No assigned trainer.")
            trainer = self.db.get(models.TrainerProfile, me.trainer_id)
            if trainer is None or trainer.user_id != peer_user_id:
                raise ForbiddenError("You can only message your assigned trainer.")
            return peer_user_id, principal.user_id

        raise ForbiddenError()

    def _owned_thread(self, principal: Principal, thread_id: str) -> models.ChatThread:
        """Allow access if the caller is a thread participant.

        Roster is enforced when *creating* a thread. Re-checking on every read/send
        breaks existing DMs after reassignment (inbox still lists the thread).
        """
        thread = self.repo.get_thread(thread_id)
        if thread is None:
            raise NotFoundError("Chat thread not found.")
        if principal.user_id not in {thread.trainer_user_id, thread.trainee_user_id}:
            raise ForbiddenError("You do not have access to this chat.")
        return thread

    def _peer_user_id(self, thread: models.ChatThread, user_id: str) -> str:
        return thread.trainee_user_id if user_id == thread.trainer_user_id else thread.trainer_user_id

    async def _after_message(
        self,
        principal: Principal | _PeerPrincipal,
        thread: models.ChatThread,
        message: models.ChatMessage,
        request: Request,
    ) -> ChatMessageOut:
        out = self._message_out(message, request)
        peer_id = self._peer_user_id(thread, principal.user_id)
        preview = build_preview(
            kind=message.kind,
            text=message.text,
            attachment_type=message.attachment_type,
            duration_seconds=message.duration_seconds,
            call_outcome=message.call_outcome,
        ) or "New message"

        if self.hub is not None:
            await self.hub.emit_message(peer_id, out.model_dump(by_alias=True, mode="json"))
            await self.hub.emit_thread_updated(
                peer_id,
                self._thread_out(thread, _PeerPrincipal(peer_id), request).model_dump(by_alias=True, mode="json"),
            )
            # Also update sender's other devices
            await self.hub.emit_thread_updated(
                principal.user_id,
                self._thread_out(thread, principal, request).model_dump(by_alias=True, mode="json"),
            )

        sender = self.db.get(models.User, principal.user_id)
        await self.push.notify_chat_message(
            recipient_user_id=peer_id,
            title=(sender.name if sender else "New message"),
            body=preview,
            thread_id=thread.id,
            message_id=message.id,
            skip_if_online=True,
        )
        return out

    def _ice_server_list(self) -> list[ChatIceServer]:
        stun = [u.strip() for u in self.settings.webrtc_stun_urls.split(",") if u.strip()]
        servers = [ChatIceServer(urls=stun)] if stun else []
        turn_urls = [u.strip() for u in self.settings.webrtc_turn_urls.split(",") if u.strip()]
        if turn_urls and self.settings.webrtc_turn_username and self.settings.webrtc_turn_credential:
            servers.append(
                ChatIceServer(
                    urls=turn_urls,
                    username=self.settings.webrtc_turn_username,
                    credential=self.settings.webrtc_turn_credential,
                )
            )
        return servers

    def _rtc_out(self, session: models.ChatRtcSession, request: Request) -> ChatRtcSessionOut:
        base = public_base(request, self.settings)
        # Prefer wss when public base is https
        if base.startswith("https://"):
            ws_base = "wss://" + base.removeprefix("https://")
        elif base.startswith("http://"):
            ws_base = "ws://" + base.removeprefix("http://")
        else:
            ws_base = base
        path = f"{ws_base}/chat/rtc/sessions/{session.id}/signal"
        return ChatRtcSessionOut(
            id=session.id,
            thread_id=session.thread_id,
            signaling_path=path,
            ice_servers=self._ice_server_list(),
            created_at=session.created_at,
        )

    def _thread_out(
        self, thread: models.ChatThread, principal: Principal | _PeerPrincipal, request: Request
    ) -> ChatThreadOut:
        if principal.user_id == thread.trainer_user_id:
            peer_id = thread.trainee_user_id
            peer_role = "trainee"
            unread = thread.trainer_unread_count
        else:
            peer_id = thread.trainer_user_id
            peer_role = "trainer"
            unread = thread.trainee_unread_count
        peer = self.db.get(models.User, peer_id)
        return ChatThreadOut(
            id=thread.id,
            peer_user_id=peer_id,
            peer_name=peer.name if peer else "User",
            peer_avatar_url=absolute_media_url(request, self.settings, getattr(peer, "avatar_url", None)),
            last_message_preview=thread.last_message_preview,
            last_message_at=thread.last_message_at,
            unread_count=int(unread or 0),
            peer_role=peer_role,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
        )

    def _message_out(self, row: models.ChatMessage, request: Request) -> ChatMessageOut:
        reactions_src = getattr(row, "reactions", None) or []
        reactions = [
            ChatReactionOut(emoji=r.emoji, user_id=r.user_id, created_at=r.created_at)
            for r in sorted(reactions_src, key=lambda x: x.created_at)
        ]
        deleted = getattr(row, "deleted_for_everyone_at", None)
        return ChatMessageOut(
            id=row.id,
            thread_id=row.thread_id,
            sender_user_id=row.sender_user_id,
            sender_role=row.sender_role,
            kind=getattr(row, "kind", None) or "text",
            text=None if deleted else row.text,
            attachment_url=(
                None if deleted else absolute_media_url(request, self.settings, row.attachment_url)
            ),
            attachment_type=None if deleted else row.attachment_type,
            duration_seconds=None if deleted else getattr(row, "duration_seconds", None),
            call_outcome=None if deleted else getattr(row, "call_outcome", None),
            client_id=row.client_id,
            created_at=row.created_at,
            delivered_at=getattr(row, "delivered_at", None),
            read_at=row.read_at,
            played_at=getattr(row, "played_at", None),
            reply_to_message_id=getattr(row, "reply_to_message_id", None),
            reply_to_text=getattr(row, "reply_to_text", None),
            reply_to_sender_name=getattr(row, "reply_to_sender_name", None),
            reactions=reactions,
            edited_at=getattr(row, "edited_at", None),
            deleted_for_everyone_at=deleted,
        )


class _PeerPrincipal:
    """Minimal stand-in when emitting thread.updated to the peer."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.role = "trainee"
        self.trainer_id = None
        self.trainee_id = None
