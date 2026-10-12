from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db import models


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_preview(
    *,
    kind: str,
    text: str | None,
    attachment_type: str | None,
    duration_seconds: int | None,
    call_outcome: str | None,
) -> str | None:
    if kind == "call_event":
        return (call_outcome or "📞 Call")[:280]
    if attachment_type == "image":
        caption = (text or "").strip()
        return (f"📷 Photo · {caption}" if caption else "📷 Photo")[:280]
    if attachment_type == "video":
        return "🎬 Video"[:280]
    if attachment_type == "voice":
        if duration_seconds and duration_seconds > 0:
            return f"🎤 Voice note · {int(duration_seconds)}s"[:280]
        return "🎤 Voice note"
    if attachment_type == "file":
        return "📎 File"
    cleaned = (text or "").strip()
    return cleaned[:280] or None


def reply_preview(
    *,
    kind: str,
    text: str | None,
    attachment_type: str | None,
    call_outcome: str | None,
    deleted: bool = False,
) -> str:
    if deleted:
        return "Original message"
    if kind == "call_event":
        return (call_outcome or "📞 Call")[:120]
    if attachment_type == "image":
        return "📷 Photo"
    if attachment_type == "video":
        return "🎬 Video"
    if attachment_type == "voice":
        return "🎤 Voice"
    if attachment_type == "file":
        return "📎 File"
    cleaned = (text or "").strip()
    return (cleaned[:120] if cleaned else "Original message")


class ChatRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_threads_for_user(self, user_id: str) -> list[models.ChatThread]:
        return list(
            self.db.scalars(
                select(models.ChatThread)
                .where(
                    or_(
                        models.ChatThread.trainer_user_id == user_id,
                        models.ChatThread.trainee_user_id == user_id,
                    )
                )
                .order_by(
                    models.ChatThread.last_message_at.desc().nullslast(),
                    models.ChatThread.updated_at.desc(),
                )
            ).all()
        )

    def get_thread(self, thread_id: str) -> models.ChatThread | None:
        return self.db.get(models.ChatThread, thread_id)

    def find_thread(self, trainer_user_id: str, trainee_user_id: str) -> models.ChatThread | None:
        return self.db.scalars(
            select(models.ChatThread).where(
                models.ChatThread.trainer_user_id == trainer_user_id,
                models.ChatThread.trainee_user_id == trainee_user_id,
            )
        ).first()

    def create_thread(self, trainer_user_id: str, trainee_user_id: str) -> models.ChatThread:
        now = _utcnow()
        row = models.ChatThread(
            id=str(uuid4()),
            trainer_user_id=trainer_user_id,
            trainee_user_id=trainee_user_id,
            last_message_at=None,
            last_message_preview=None,
            trainer_unread_count=0,
            trainee_unread_count=0,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_message(self, message_id: str) -> models.ChatMessage | None:
        return self.db.scalars(
            select(models.ChatMessage)
            .where(models.ChatMessage.id == message_id)
            .options(joinedload(models.ChatMessage.reactions))
        ).first()

    def get_message_by_client_id(
        self, thread_id: str, client_id: str, *, sender_user_id: str | None = None
    ) -> models.ChatMessage | None:
        stmt = (
            select(models.ChatMessage)
            .where(
                models.ChatMessage.thread_id == thread_id,
                models.ChatMessage.client_id == client_id,
            )
            .options(joinedload(models.ChatMessage.reactions))
        )
        if sender_user_id:
            stmt = stmt.where(models.ChatMessage.sender_user_id == sender_user_id)
        return self.db.scalars(stmt).first()

    def list_messages(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        before_id: str | None = None,
    ) -> list[models.ChatMessage]:
        stmt = (
            select(models.ChatMessage)
            .where(models.ChatMessage.thread_id == thread_id)
            .options(joinedload(models.ChatMessage.reactions))
        )
        if before_id:
            anchor = self.db.get(models.ChatMessage, before_id)
            if anchor is not None and anchor.thread_id == thread_id:
                stmt = stmt.where(
                    or_(
                        models.ChatMessage.created_at < anchor.created_at,
                        and_(
                            models.ChatMessage.created_at == anchor.created_at,
                            models.ChatMessage.id < anchor.id,
                        ),
                    )
                )
        rows = list(
            self.db.scalars(
                stmt.order_by(models.ChatMessage.created_at.desc(), models.ChatMessage.id.desc()).limit(limit)
            ).unique().all()
        )
        rows.reverse()
        return rows

    def add_message(
        self,
        thread: models.ChatThread,
        *,
        sender_user_id: str,
        sender_role: str,
        kind: str = "text",
        text: str | None = None,
        attachment_url: str | None = None,
        attachment_type: str | None = None,
        duration_seconds: int | None = None,
        call_outcome: str | None = None,
        client_id: str | None = None,
        reply_to_message_id: str | None = None,
        reply_to_text: str | None = None,
        reply_to_sender_name: str | None = None,
        bump_unread: bool = True,
    ) -> models.ChatMessage:
        now = _utcnow()
        preview = build_preview(
            kind=kind,
            text=text,
            attachment_type=attachment_type,
            duration_seconds=duration_seconds,
            call_outcome=call_outcome,
        )

        message = models.ChatMessage(
            id=str(uuid4()),
            thread_id=thread.id,
            sender_user_id=sender_user_id,
            sender_role=sender_role,
            kind=kind,
            text=text,
            attachment_url=attachment_url,
            attachment_type=attachment_type,
            duration_seconds=duration_seconds,
            call_outcome=call_outcome,
            client_id=client_id,
            created_at=now,
            delivered_at=None,
            read_at=None,
            played_at=None,
            reply_to_message_id=reply_to_message_id,
            reply_to_text=reply_to_text,
            reply_to_sender_name=reply_to_sender_name,
            edited_at=None,
            deleted_for_everyone_at=None,
        )
        thread.last_message_at = now
        thread.last_message_preview = preview
        thread.updated_at = now
        if bump_unread:
            if sender_role == "trainer":
                thread.trainee_unread_count = int(thread.trainee_unread_count or 0) + 1
            else:
                thread.trainer_unread_count = int(thread.trainer_unread_count or 0) + 1

        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        self.db.refresh(thread)
        return message

    def mark_delivered(
        self, thread: models.ChatThread, *, delivered_by_user_id: str, up_to_message_id: str
    ) -> tuple[int, datetime | None]:
        up_to = self.db.get(models.ChatMessage, up_to_message_id)
        if up_to is None or up_to.thread_id != thread.id:
            return 0, None
        now = _utcnow()
        rows = list(
            self.db.scalars(
                select(models.ChatMessage).where(
                    models.ChatMessage.thread_id == thread.id,
                    models.ChatMessage.sender_user_id != delivered_by_user_id,
                    models.ChatMessage.delivered_at.is_(None),
                    models.ChatMessage.created_at <= up_to.created_at,
                )
            ).all()
        )
        for row in rows:
            row.delivered_at = now
        if rows:
            thread.updated_at = now
            self.db.commit()
        return len(rows), (now if rows else None)

    def mark_read(self, thread: models.ChatThread, *, reader_user_id: str, up_to_message_id: str) -> int:
        up_to = self.db.get(models.ChatMessage, up_to_message_id)
        if up_to is None or up_to.thread_id != thread.id:
            return 0
        now = _utcnow()
        rows = list(
            self.db.scalars(
                select(models.ChatMessage).where(
                    models.ChatMessage.thread_id == thread.id,
                    models.ChatMessage.sender_user_id != reader_user_id,
                    models.ChatMessage.created_at <= up_to.created_at,
                    or_(
                        models.ChatMessage.read_at.is_(None),
                        models.ChatMessage.delivered_at.is_(None),
                    ),
                )
            ).all()
        )
        for row in rows:
            if row.delivered_at is None:
                row.delivered_at = now
            if row.read_at is None:
                row.read_at = now
        if reader_user_id == thread.trainer_user_id:
            thread.trainer_unread_count = 0
        elif reader_user_id == thread.trainee_user_id:
            thread.trainee_unread_count = 0
        thread.updated_at = now
        self.db.commit()
        return len(rows)

    def mark_played(
        self, message: models.ChatMessage, *, played_by_user_id: str
    ) -> datetime | None:
        if message.played_at is not None:
            return message.played_at
        now = _utcnow()
        message.played_at = now
        self.db.commit()
        self.db.refresh(message)
        return now

    def upsert_reaction(
        self, message: models.ChatMessage, *, user_id: str, emoji: str
    ) -> models.ChatMessageReaction:
        now = _utcnow()
        existing = self.db.scalars(
            select(models.ChatMessageReaction).where(
                models.ChatMessageReaction.message_id == message.id,
                models.ChatMessageReaction.user_id == user_id,
            )
        ).first()
        if existing is not None:
            existing.emoji = emoji
            existing.created_at = now
            self.db.commit()
            self.db.refresh(existing)
            return existing
        row = models.ChatMessageReaction(
            id=str(uuid4()),
            message_id=message.id,
            user_id=user_id,
            emoji=emoji,
            created_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def remove_reaction(self, message: models.ChatMessage, *, user_id: str, emoji: str) -> bool:
        row = self.db.scalars(
            select(models.ChatMessageReaction).where(
                models.ChatMessageReaction.message_id == message.id,
                models.ChatMessageReaction.user_id == user_id,
                models.ChatMessageReaction.emoji == emoji,
            )
        ).first()
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def list_reactions(self, message_id: str) -> list[models.ChatMessageReaction]:
        return list(
            self.db.scalars(
                select(models.ChatMessageReaction)
                .where(models.ChatMessageReaction.message_id == message_id)
                .order_by(models.ChatMessageReaction.created_at.asc())
            ).all()
        )

    def soft_delete_everyone(self, message: models.ChatMessage) -> models.ChatMessage:
        now = _utcnow()
        message.deleted_for_everyone_at = now
        message.text = None
        message.attachment_url = None
        message.attachment_type = None
        message.duration_seconds = None
        message.call_outcome = None
        self.db.commit()
        self.db.refresh(message)
        return message

    def edit_text(self, message: models.ChatMessage, text: str) -> models.ChatMessage:
        now = _utcnow()
        message.text = text
        message.edited_at = now
        self.db.commit()
        self.db.refresh(message)
        return message

    def create_rtc_session(self, thread_id: str, created_by_user_id: str) -> models.ChatRtcSession:
        now = _utcnow()
        row = models.ChatRtcSession(
            id=str(uuid4()),
            thread_id=thread_id,
            created_by_user_id=created_by_user_id,
            status="active",
            created_at=now,
            ended_at=None,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_rtc_session(self, session_id: str) -> models.ChatRtcSession | None:
        return self.db.get(models.ChatRtcSession, session_id)

    def list_active_rtc_for_thread(self, thread_id: str) -> list[models.ChatRtcSession]:
        return list(
            self.db.scalars(
                select(models.ChatRtcSession).where(
                    models.ChatRtcSession.thread_id == thread_id,
                    models.ChatRtcSession.status == "active",
                )
            ).all()
        )

    def list_incoming_rtc_for_user(self, user_id: str) -> list[models.ChatRtcSession]:
        """Active sessions on my threads that someone else started (ringing for me)."""
        return list(
            self.db.scalars(
                select(models.ChatRtcSession)
                .join(models.ChatThread, models.ChatThread.id == models.ChatRtcSession.thread_id)
                .where(
                    models.ChatRtcSession.status == "active",
                    models.ChatRtcSession.created_by_user_id != user_id,
                    or_(
                        models.ChatThread.trainer_user_id == user_id,
                        models.ChatThread.trainee_user_id == user_id,
                    ),
                )
                .order_by(models.ChatRtcSession.created_at.desc())
            ).all()
        )

    def end_rtc_session(self, session: models.ChatRtcSession) -> models.ChatRtcSession:
        session.status = "ended"
        session.ended_at = _utcnow()
        self.db.commit()
        self.db.refresh(session)
        return session
