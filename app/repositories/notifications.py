from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.db import models


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotificationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        user_id: str,
        type: str,
        title: str,
        body: str,
        data: dict | None = None,
    ) -> models.AppNotification:
        row = models.AppNotification(
            id=str(uuid4()),
            user_id=user_id,
            type=type[:32],
            title=title[:160],
            body=body[:500],
            data=data or {},
            read_at=None,
            created_at=_utcnow(),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        before_id: str | None = None,
    ) -> list[models.AppNotification]:
        stmt = select(models.AppNotification).where(models.AppNotification.user_id == user_id)
        if before_id:
            anchor = self.db.get(models.AppNotification, before_id)
            if anchor is not None and anchor.user_id == user_id:
                stmt = stmt.where(
                    or_(
                        models.AppNotification.created_at < anchor.created_at,
                        and_(
                            models.AppNotification.created_at == anchor.created_at,
                            models.AppNotification.id < anchor.id,
                        ),
                    )
                )
        rows = list(
            self.db.scalars(
                stmt.order_by(
                    models.AppNotification.created_at.desc(),
                    models.AppNotification.id.desc(),
                ).limit(limit)
            ).all()
        )
        return rows

    def unread_count(self, user_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(models.AppNotification)
                .where(
                    models.AppNotification.user_id == user_id,
                    models.AppNotification.read_at.is_(None),
                )
            )
            or 0
        )

    def get(self, notification_id: str) -> models.AppNotification | None:
        return self.db.get(models.AppNotification, notification_id)

    def mark_read(self, row: models.AppNotification) -> models.AppNotification:
        if row.read_at is None:
            row.read_at = _utcnow()
            self.db.commit()
            self.db.refresh(row)
        return row

    def mark_all_read(self, user_id: str) -> int:
        now = _utcnow()
        rows = list(
            self.db.scalars(
                select(models.AppNotification).where(
                    models.AppNotification.user_id == user_id,
                    models.AppNotification.read_at.is_(None),
                )
            ).all()
        )
        for row in rows:
            row.read_at = now
        self.db.commit()
        return len(rows)

    def delete_for_user(self, user_id: str, notification_id: str) -> bool:
        """Hard-delete one row owned by user. Idempotent — False if missing/not owned."""
        row = self.db.get(models.AppNotification, notification_id)
        if row is None or row.user_id != user_id:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def delete_all_for_user(self, user_id: str) -> int:
        result = self.db.execute(
            delete(models.AppNotification).where(models.AppNotification.user_id == user_id)
        )
        self.db.commit()
        return int(result.rowcount or 0)


class PushTokenRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(
        self,
        *,
        user_id: str,
        token: str,
        platform: str,
        device_name: str | None = None,
        app_version: str | None = None,
    ) -> models.DevicePushToken:
        now = _utcnow()
        existing = self.db.scalars(
            select(models.DevicePushToken).where(
                models.DevicePushToken.user_id == user_id,
                models.DevicePushToken.token == token,
            )
        ).first()
        if existing:
            existing.platform = platform
            existing.device_name = device_name
            existing.app_version = app_version
            existing.updated_at = now
            self.db.commit()
            self.db.refresh(existing)
            return existing

        # Same physical token moved to another account → reassign
        other = self.db.scalars(
            select(models.DevicePushToken).where(models.DevicePushToken.token == token)
        ).first()
        if other is not None:
            other.user_id = user_id
            other.platform = platform
            other.device_name = device_name
            other.app_version = app_version
            other.updated_at = now
            self.db.commit()
            self.db.refresh(other)
            return other

        row = models.DevicePushToken(
            id=str(uuid4()),
            user_id=user_id,
            token=token,
            platform=platform,
            device_name=device_name,
            app_version=app_version,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_token(self, user_id: str, token: str) -> bool:
        row = self.db.scalars(
            select(models.DevicePushToken).where(
                models.DevicePushToken.user_id == user_id,
                models.DevicePushToken.token == token,
            )
        ).first()
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def list_for_user(self, user_id: str) -> list[models.DevicePushToken]:
        return list(
            self.db.scalars(
                select(models.DevicePushToken).where(models.DevicePushToken.user_id == user_id)
            ).all()
        )
