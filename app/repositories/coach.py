from datetime import datetime, timezone
from uuid import uuid4
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_citations(citations: list | None) -> list | None:
    """Ensure citations are JSONB-safe (no NaN/Inf)."""
    if not citations:
        return citations
    cleaned: list = []
    for item in citations:
        if not isinstance(item, dict):
            cleaned.append(item)
            continue
        row = dict(item)
        if "score" in row:
            try:
                score = float(row["score"])
            except (TypeError, ValueError):
                score = 0.0
            row["score"] = round(score, 4) if math.isfinite(score) else 0.0
        cleaned.append(row)
    return cleaned


class CoachRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_conversations(self, user_id: str) -> list[models.CoachConversation]:
        return list(
            self.db.scalars(
                select(models.CoachConversation)
                .where(models.CoachConversation.user_id == user_id)
                .order_by(models.CoachConversation.updated_at.desc())
            ).all()
        )

    def get_conversation(self, conversation_id: str, user_id: str) -> models.CoachConversation | None:
        row = self.db.get(models.CoachConversation, conversation_id)
        if row is None or row.user_id != user_id:
            return None
        return row

    def get_conversation_by_id(self, conversation_id: str) -> models.CoachConversation | None:
        return self.db.get(models.CoachConversation, conversation_id)

    def list_all_messages(self, conversation_id: str) -> list[models.CoachMessage]:
        return list(
            self.db.scalars(
                select(models.CoachMessage)
                .where(models.CoachMessage.conversation_id == conversation_id)
                .order_by(models.CoachMessage.created_at.asc())
            ).all()
        )

    def list_open_rtc_sessions_for_conversation(
        self, conversation_id: str, user_id: str
    ) -> list[models.CoachRtcSession]:
        return list(
            self.db.scalars(
                select(models.CoachRtcSession).where(
                    models.CoachRtcSession.conversation_id == conversation_id,
                    models.CoachRtcSession.user_id == user_id,
                    models.CoachRtcSession.status == "open",
                )
            ).all()
        )

    def delete_conversation(self, conversation: models.CoachConversation) -> None:
        self.db.delete(conversation)
        self.db.commit()

    def create_conversation(self, user_id: str, role: str, title: str = "AI Coach") -> models.CoachConversation:
        now = _utcnow()
        row = models.CoachConversation(
            id=str(uuid4()),
            user_id=user_id,
            role=role,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_messages(self, conversation_id: str, limit: int = 40) -> list[models.CoachMessage]:
        rows = list(
            self.db.scalars(
                select(models.CoachMessage)
                .where(models.CoachMessage.conversation_id == conversation_id)
                .order_by(models.CoachMessage.created_at.desc())
                .limit(limit)
            ).all()
        )
        rows.reverse()
        return rows

    def add_message(
        self,
        conversation: models.CoachConversation,
        *,
        role: str,
        content: str,
        modality: str = "text",
        audio_url: str | None = None,
        image_url: str | None = None,
        citations: list | None = None,
    ) -> models.CoachMessage:
        now = _utcnow()
        message = models.CoachMessage(
            id=str(uuid4()),
            conversation_id=conversation.id,
            role=role,
            content=content,
            modality=modality,
            audio_url=audio_url,
            image_url=image_url,
            citations=_sanitize_citations(citations),
            created_at=now,
        )
        conversation.updated_at = now
        if role == "user" and conversation.title == "AI Coach":
            conversation.title = content.strip()[:48] or ("Photo" if image_url else "AI Coach")
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def create_rtc_session(
        self, user_id: str, conversation_id: str | None
    ) -> models.CoachRtcSession:
        row = models.CoachRtcSession(
            id=str(uuid4()),
            user_id=user_id,
            conversation_id=conversation_id,
            status="open",
            created_at=_utcnow(),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_rtc_session(self, session_id: str, user_id: str) -> models.CoachRtcSession | None:
        row = self.db.get(models.CoachRtcSession, session_id)
        if row is None or row.user_id != user_id:
            return None
        return row

    def close_rtc_session(self, session: models.CoachRtcSession) -> models.CoachRtcSession:
        session.status = "closed"
        session.closed_at = _utcnow()
        self.db.commit()
        self.db.refresh(session)
        return session
