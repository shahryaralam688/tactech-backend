from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel


class PushTokenRegisterRequest(APIModel):
    token: str = Field(min_length=8, max_length=512)
    platform: str = Field(default="ios", max_length=16)  # ios | android
    device_name: str | None = Field(default=None, max_length=120)
    app_version: str | None = Field(default=None, max_length=32)


class PushTokenOut(APIModel):
    id: str
    platform: str
    device_name: str | None = None
    app_version: str | None = None
    created_at: datetime
    updated_at: datetime


class PushTokenDeleteRequest(APIModel):
    token: str = Field(min_length=8, max_length=512)


class AppNotificationOut(APIModel):
    id: str
    type: str
    title: str
    body: str
    data: dict[str, Any] = Field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime


class AppNotificationPage(APIModel):
    items: list[AppNotificationOut]
    next_cursor: str | None = None
    unread_count: int = 0


class NotificationUnreadCountOut(APIModel):
    unread_count: int


class NotificationReadRequest(APIModel):
    """Mark one or all as read. If notificationId omitted, mark all unread."""

    notification_id: str | None = Field(default=None, max_length=64)


class NotificationDeleteRequest(APIModel):
    """Delete one notification, or all when notificationId is null/omitted."""

    notification_id: str | None = Field(default=None, max_length=64)
