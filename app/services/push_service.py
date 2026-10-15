"""Notifications: in-app inbox + Socket.IO + APNs (when configured)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.repositories.notifications import NotificationRepository, PushTokenRepository
from app.repositories.preference import PreferenceRepository
from app.schemas.notifications import (
    AppNotificationOut,
    AppNotificationPage,
    NotificationUnreadCountOut,
    PushTokenOut,
)
from app.schemas.preferences import NotificationPreferences
from app.services.apns import send_alert
from app.services.preference_service import default_notifications

if TYPE_CHECKING:
    from app.realtime.chat_hub import ChatHub

log = get_logger("tactech.push")

# pushType → NotificationPreferences field for APNs (None = master `push` only).
# vibrations / sound are client-only and never appear here.
_PUSH_TYPE_PREF: dict[str, str | None] = {
    "chat": "chat_messages",
    "chat_call": "chat_calls",
    "ai_coach": "ai_coach",
    "metrics": "metrics",
    "workout": "metrics",
    # Plan assignment alerts share the metrics family for APNs
    "plan_assigned": "metrics",
    "plan_unassigned": "metrics",
    "plan_updated": "metrics",
    "app_update": "app_update",
    "resources": "resources",
    "offers": "offers_device",
    # Coaching-critical — master push only (inbox always created)
    "coach_follow": None,
    "coach_follow_accepted": None,
    "coach_follow_declined": None,
    "coach_follow_ended": None,
    "trainee_left": None,
    "trainer_removed": None,
    "relationship_ended": None,
    "join_request": None,
    "join_request_accepted": None,
    "join_request_rejected": None,
    "join_request_cancelled": None,
}

# Types that always get an inbox row even when remote push is skipped
_INBOX_ALWAYS = frozenset(
    {
        "chat",
        "chat_call",
        "coach_follow",
        "coach_follow_accepted",
        "coach_follow_declined",
        "coach_follow_ended",
        "trainee_left",
        "trainer_removed",
        "relationship_ended",
        "plan_assigned",
        "plan_unassigned",
        "plan_updated",
        "join_request",
        "join_request_accepted",
        "join_request_rejected",
        "join_request_cancelled",
    }
)

# Invalid-token reasons from APNs → delete stored device token
_APNS_INVALID_REASONS = frozenset(
    {
        "BadDeviceToken",
        "Unregistered",
        "DeviceTokenNotForTopic",
        "ExpiredToken",
    }
)


def flatten_notification_data(data: dict[str, Any] | None) -> dict[str, str]:
    """iOS flattens scalars — store string values only."""
    out: dict[str, str] = {}
    for key, value in (data or {}).items():
        if value is None:
            continue
        out[str(key)] = value if isinstance(value, str) else str(value)
    return out


class PushService:
    """Create inbox rows, respect prefs, queue remote push, optionally emit Socket."""

    def __init__(self, db: Session, hub: ChatHub | None = None) -> None:
        self.db = db
        self.hub = hub
        self.notifications = NotificationRepository(db)
        self.tokens = PushTokenRepository(db)
        self.prefs = PreferenceRepository(db)

    # ── Device tokens ──────────────────────────────────────────────

    def register_token(
        self,
        user_id: str,
        *,
        token: str,
        platform: str,
        device_name: str | None = None,
        app_version: str | None = None,
    ) -> PushTokenOut:
        cleaned = token.strip()
        plat = (platform or "ios").strip().lower()
        if plat not in {"ios", "android"}:
            raise ValidationAppError("platform must be ios or android.", fields={"platform": "invalid"})
        if len(cleaned) < 8:
            raise ValidationAppError("Invalid push token.", fields={"token": "invalid"})
        row = self.tokens.upsert(
            user_id=user_id,
            token=cleaned,
            platform=plat,
            device_name=(device_name or None),
            app_version=(app_version or None),
        )
        return PushTokenOut(
            id=row.id,
            platform=row.platform,
            device_name=row.device_name,
            app_version=row.app_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def unregister_token(self, user_id: str, token: str) -> None:
        self.tokens.delete_token(user_id, token.strip())

    def list_tokens(self, user_id: str) -> list[PushTokenOut]:
        return [
            PushTokenOut(
                id=row.id,
                platform=row.platform,
                device_name=row.device_name,
                app_version=row.app_version,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in self.tokens.list_for_user(user_id)
        ]

    # ── Inbox ──────────────────────────────────────────────────────

    def list_inbox(
        self, user_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> AppNotificationPage:
        limit = max(1, min(limit, 100))
        rows = self.notifications.list_for_user(user_id, limit=limit + 1, before_id=cursor)
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = rows[-1].id
        return AppNotificationPage(
            items=[self._out(r) for r in rows],
            next_cursor=next_cursor,
            unread_count=self.notifications.unread_count(user_id),
        )

    def unread_count(self, user_id: str) -> NotificationUnreadCountOut:
        return NotificationUnreadCountOut(unread_count=self.notifications.unread_count(user_id))

    def mark_read(self, user_id: str, notification_id: str | None) -> NotificationUnreadCountOut:
        if notification_id:
            row = self.notifications.get(notification_id)
            if row is None or row.user_id != user_id:
                raise NotFoundError("Notification not found.")
            self.notifications.mark_read(row)
        else:
            self.notifications.mark_all_read(user_id)
        return self.unread_count(user_id)

    def delete(
        self, user_id: str, notification_id: str | None
    ) -> NotificationUnreadCountOut:
        """Delete one (idempotent) or clear entire inbox. Always 200 with unreadCount."""
        if notification_id:
            self.notifications.delete_for_user(user_id, notification_id)
        else:
            self.notifications.delete_all_for_user(user_id)
        return self.unread_count(user_id)

    # ── Preference gate (central) ──────────────────────────────────

    def prefs_for(self, user_id: str) -> NotificationPreferences:
        row = self.prefs.get(user_id)
        if row is None:
            return NotificationPreferences()
        try:
            merged = {**default_notifications(), **(row.notifications or {})}
            return NotificationPreferences.model_validate(merged)
        except Exception:
            return NotificationPreferences()

    def should_send_push(self, user_id: str, push_type: str) -> bool:
        """True iff remote APNs/FCM should be attempted for this user + type."""
        return self._should_send_push(self.prefs_for(user_id), push_type)

    @staticmethod
    def _should_send_push(prefs: NotificationPreferences, push_type: str) -> bool:
        """Central APNs gate. Inbox / Socket are decided separately in ``_deliver``.

        | type | requires |
        |------|----------|
        | * | push == true |
        | chat | chatMessages |
        | chat_call | chatCalls |
        | ai_coach | aiCoach |
        | metrics / workout / plan_* | metrics |
        | app_update | appUpdate |
        | resources | resources |
        | offers | offersDevice |
        | join_* / relationship_ended / follow_* | push master only |
        """
        if not prefs.push:
            return False
        key = _PUSH_TYPE_PREF.get(push_type)
        if key is None:
            # Unknown or master-only type
            return True
        return bool(getattr(prefs, key, True))

    # ── Emit helpers used by chat / coach / jobs ───────────────────

    async def notify_chat_message(
        self,
        *,
        recipient_user_id: str,
        title: str,
        body: str,
        thread_id: str,
        message_id: str | None = None,
        skip_if_online: bool = True,
    ) -> models.AppNotification | None:
        data = {"type": "chat", "threadId": thread_id, "messageId": message_id}
        return await self._deliver(
            recipient_user_id=recipient_user_id,
            notif_type="chat",
            title=title,
            body=body,
            data=data,
            skip_remote_if_online=skip_if_online,
            high_priority=False,
        )

    async def notify_chat_call(
        self,
        *,
        recipient_user_id: str,
        title: str,
        body: str,
        thread_id: str,
        session_id: str,
        from_user_id: str,
        from_name: str,
        signaling_path: str | None = None,
        high_priority: bool = True,
        skip_if_online: bool = True,
    ) -> models.AppNotification | None:
        data: dict[str, Any] = {
            "type": "chat_call",
            "threadId": thread_id,
            "sessionId": session_id,
            "fromUserId": from_user_id,
            "fromName": from_name,
        }
        if signaling_path:
            data["signalingPath"] = signaling_path
        return await self._deliver(
            recipient_user_id=recipient_user_id,
            notif_type="chat_call",
            title=title,
            body=body,
            data=data,
            skip_remote_if_online=skip_if_online,
            high_priority=high_priority,
        )

    async def notify_ai_coach(
        self,
        *,
        recipient_user_id: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> models.AppNotification | None:
        return await self._deliver(
            recipient_user_id=recipient_user_id,
            notif_type="ai_coach",
            title=title,
            body=body,
            data=data or {"type": "ai_coach"},
            skip_remote_if_online=False,
            high_priority=False,
        )

    async def notify_metrics(
        self,
        *,
        recipient_user_id: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        notif_type: str = "metrics",
    ) -> models.AppNotification | None:
        """Workout / progress reminders (`metrics` or `workout`)."""
        kind = notif_type if notif_type in {"metrics", "workout"} else "metrics"
        return await self._deliver(
            recipient_user_id=recipient_user_id,
            notif_type=kind,
            title=title,
            body=body,
            data=data or {"type": kind},
            skip_remote_if_online=False,
            high_priority=False,
        )

    async def notify_app_update(
        self,
        *,
        recipient_user_id: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> models.AppNotification | None:
        return await self._deliver(
            recipient_user_id=recipient_user_id,
            notif_type="app_update",
            title=title,
            body=body,
            data=data or {"type": "app_update"},
            skip_remote_if_online=False,
            high_priority=False,
        )

    async def notify_resources(
        self,
        *,
        recipient_user_id: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> models.AppNotification | None:
        return await self._deliver(
            recipient_user_id=recipient_user_id,
            notif_type="resources",
            title=title,
            body=body,
            data=data or {"type": "resources"},
            skip_remote_if_online=False,
            high_priority=False,
        )

    async def notify_offers(
        self,
        *,
        recipient_user_id: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> models.AppNotification | None:
        return await self._deliver(
            recipient_user_id=recipient_user_id,
            notif_type="offers",
            title=title,
            body=body,
            data=data or {"type": "offers"},
            skip_remote_if_online=False,
            high_priority=False,
        )

    async def notify_generic(
        self,
        *,
        recipient_user_id: str,
        notif_type: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        pref_key: str | None = None,
        skip_if_online: bool = False,
    ) -> models.AppNotification | None:
        # pref_key kept for callers; gating uses notif_type via should_send_push.
        _ = pref_key
        return await self._deliver(
            recipient_user_id=recipient_user_id,
            notif_type=notif_type,
            title=title,
            body=body,
            data=data or {"type": notif_type},
            skip_remote_if_online=skip_if_online,
            high_priority=False,
        )

    def emit_notification_created_sync(self, user_id: str, payload: dict[str, Any]) -> None:
        """Emit ``notification.created`` to personal room ``user:{userId}`` (/ + /chat)."""
        if self.hub is None:
            return

        async def _go() -> None:
            await self.hub.emit_notification(user_id, payload)  # type: ignore[union-attr]

        try:
            from anyio import from_thread

            from_thread.run(_go)
            return
        except RuntimeError:
            pass

        # Fallback: dedicated thread + fresh event loop (never fire-and-forget on request session)
        import concurrent.futures

        def _run() -> None:
            asyncio.run(_go())

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(_run).result(timeout=5)
        except Exception:
            log.exception("notification_created_emit_failed", user_id=user_id)

    def notify_inbox_sync(
        self,
        *,
        recipient_user_id: str,
        notif_type: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> models.AppNotification:
        """Always create inbox + emit Socket on this thread (no APNs required).

        Used for coaching-critical events (join_request, etc.) where notify_sync's
        async bridge must not drop the durable row.
        """
        flat = flatten_notification_data(data)
        if "type" not in flat:
            flat["type"] = notif_type
        row = self.notifications.create(
            user_id=recipient_user_id,
            type=notif_type,
            title=title,
            body=body,
            data=flat,
            commit=commit,
        )
        if commit:
            # Already committed inside create
            pass
        else:
            self.db.flush()
        out = self._out(row)
        payload = out.model_dump(by_alias=True, mode="json")
        try:
            self.emit_notification_created_sync(recipient_user_id, payload)
        except Exception:
            log.exception(
                "notify_inbox_socket_failed",
                user_id=recipient_user_id,
                type=notif_type,
            )
        log.info(
            "notify_inbox_sync",
            user_id=recipient_user_id,
            type=notif_type,
            notification_id=row.id,
        )
        return row

    def notify_sync(
        self,
        *,
        recipient_user_id: str,
        notif_type: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        skip_if_online: bool = False,
    ) -> models.AppNotification | None:
        """Sync entry for FastAPI sync routes.

        Join / relationship types use the sync inbox path so a failed async
        bridge cannot drop the durable notification the trainer must see.
        """
        _critical = frozenset(
            {
                "join_request",
                "join_request_accepted",
                "join_request_rejected",
                "join_request_cancelled",
                "relationship_ended",
            }
        )
        if notif_type in _critical:
            row = self.notify_inbox_sync(
                recipient_user_id=recipient_user_id,
                notif_type=notif_type,
                title=title,
                body=body,
                data=data,
                commit=True,
            )
            # Best-effort APNs only (prefs-gated); never re-create inbox
            prefs = self.prefs_for(recipient_user_id)
            if self._should_send_push(prefs, notif_type):
                try:
                    flat = flatten_notification_data(data)
                    if "type" not in flat:
                        flat["type"] = notif_type
                    online = self.hub.is_online(recipient_user_id) if self.hub else False
                    if not (skip_if_online and online):
                        tokens = self.tokens.list_for_user(recipient_user_id)
                        if tokens:
                            badge = self.notifications.unread_count(recipient_user_id)

                            async def _send() -> None:
                                await self._dispatch_remote(
                                    tokens=tokens,
                                    title=title,
                                    body=body,
                                    badge=badge,
                                    data=flat,
                                    high_priority=False,
                                )

                            try:
                                from anyio import from_thread

                                from_thread.run(_send)
                            except RuntimeError:
                                pass
                except Exception:
                    log.exception("notify_sync_apns_failed", type=notif_type)
            return row

        async def _go() -> models.AppNotification | None:
            return await self.notify_generic(
                recipient_user_id=recipient_user_id,
                notif_type=notif_type,
                title=title,
                body=body,
                data=data,
                skip_if_online=skip_if_online,
            )

        try:
            from anyio import from_thread

            return from_thread.run(_go)
        except RuntimeError:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(_go())
            # Last resort: sync inbox-only so we never silently drop
            log.warning("notify_sync_fallback_inbox_only", type=notif_type)
            return self.notify_inbox_sync(
                recipient_user_id=recipient_user_id,
                notif_type=notif_type,
                title=title,
                body=body,
                data=data,
                commit=True,
            )

    def emit_relationship_changed_sync(
        self,
        *,
        user_ids: list[str],
        action: str,
        reason: str,
        trainer_user_id: str,
        trainee_user_id: str,
        trainee_profile_id: str | None = None,
        occurred_at: str | None = None,
    ) -> None:
        """Emit Socket ``relationship.changed`` to personal rooms ``user:{id}`` (/ + /chat)."""
        if self.hub is None:
            return
        from datetime import datetime, timezone

        occurred = occurred_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload: dict[str, Any] = {
            "action": action,
            "reason": reason,
            "trainerUserId": trainer_user_id,
            "traineeUserId": trainee_user_id,
            "occurredAt": occurred,
        }
        if trainee_profile_id:
            payload["traineeProfileId"] = trainee_profile_id

        targets = list(dict.fromkeys(uid for uid in user_ids if uid))

        async def _go() -> None:
            for uid in targets:
                try:
                    await self.hub.emit_relationship_changed(uid, payload)  # type: ignore[union-attr]
                except Exception:
                    log.exception("relationship_changed_emit_failed", user_id=uid, action=action)

        try:
            from anyio import from_thread

            from_thread.run(_go)
        except RuntimeError:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(_go())
            else:
                asyncio.create_task(_go())

    def notify_relationship_ended_sync(
        self,
        *,
        peer_user_id: str,
        actor_user_id: str,
        reason: str,
        title: str,
        body: str,
        trainer_user_id: str,
        trainee_user_id: str,
        trainee_profile_id: str | None = None,
        trainee_name: str | None = None,
        trainer_name: str | None = None,
        occurred_at: str | None = None,
    ) -> models.AppNotification | None:
        """Inbox ``relationship_ended`` + ``notification.created`` + ``relationship.changed``.

        Peer is required; actor also gets ``relationship.changed`` for multi-device refresh.
        """
        data: dict[str, Any] = {
            "type": "relationship_ended",
            "reason": reason,
            "trainerUserId": trainer_user_id,
            "traineeUserId": trainee_user_id,
        }
        if trainee_profile_id:
            data["traineeProfileId"] = trainee_profile_id
        if trainee_name:
            data["traineeName"] = trainee_name
        if trainer_name:
            data["trainerName"] = trainer_name

        row = self.notify_sync(
            recipient_user_id=peer_user_id,
            notif_type="relationship_ended",
            title=title,
            body=body,
            data=data,
        )
        self.emit_relationship_changed_sync(
            user_ids=[peer_user_id, actor_user_id],
            action="unlinked",
            reason=reason,
            trainer_user_id=trainer_user_id,
            trainee_user_id=trainee_user_id,
            trainee_profile_id=trainee_profile_id,
            occurred_at=occurred_at,
        )
        return row

    def emit_plan_assignment_changed_sync(
        self,
        *,
        user_ids: list[str],
        action: str,
        plan_id: str,
        plan_title: str,
        trainer_user_id: str,
        trainee_user_id: str,
        trainee_profile_id: str | None = None,
        occurred_at: str | None = None,
    ) -> None:
        """Emit Socket ``plan.assignment.changed`` to personal rooms ``user:{id}`` (/ + /chat)."""
        if self.hub is None:
            return
        from datetime import datetime, timezone

        occurred = occurred_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload: dict[str, Any] = {
            "action": action,
            "planId": plan_id,
            "planTitle": plan_title,
            "trainerUserId": trainer_user_id,
            "traineeUserId": trainee_user_id,
            "occurredAt": occurred,
        }
        if trainee_profile_id:
            payload["traineeProfileId"] = trainee_profile_id

        targets = list(dict.fromkeys(uid for uid in user_ids if uid))

        async def _go() -> None:
            for uid in targets:
                try:
                    await self.hub.emit_plan_assignment_changed(uid, payload)  # type: ignore[union-attr]
                except Exception:
                    log.exception("plan_assignment_changed_emit_failed", user_id=uid, action=action)

        try:
            from anyio import from_thread

            from_thread.run(_go)
        except RuntimeError:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(_go())
            else:
                asyncio.create_task(_go())

    def notify_plan_assignment_changed_sync(
        self,
        *,
        action: str,
        peer_trainee_user_id: str,
        actor_trainer_user_id: str | None = None,
        plan_id: str,
        plan_title: str,
        trainer_user_id: str,
        trainee_user_id: str,
        trainee_profile_id: str,
        trainer_name: str | None = None,
        occurred_at: str | None = None,
    ) -> models.AppNotification | None:
        """Inbox plan_* + ``notification.created`` + ``plan.assignment.changed``.

        ``action``: assigned | unassigned | updated
        """
        title_map = {
            "assigned": "New workout plan",
            "unassigned": "Plan removed",
            "updated": "Plan updated",
        }
        type_map = {
            "assigned": "plan_assigned",
            "unassigned": "plan_unassigned",
            "updated": "plan_updated",
        }
        notif_type = type_map.get(action)
        if not notif_type:
            raise ValueError(f"Unsupported plan assignment action: {action}")

        name = trainer_name or "Your trainer"
        title_text = plan_title or "workout plan"
        if action == "assigned":
            body = f'{name} assigned you "{title_text}".'
        elif action == "unassigned":
            body = "Your assigned workout plan was removed."
        else:
            body = f'"{title_text}" was updated by your trainer.'

        data: dict[str, Any] = {
            "type": notif_type,
            "action": action,
            "planId": plan_id,
            "planTitle": title_text,
            "trainerUserId": trainer_user_id,
            "traineeUserId": trainee_user_id,
            "traineeProfileId": trainee_profile_id,
        }
        if trainer_name:
            data["trainerName"] = trainer_name

        row = self.notify_sync(
            recipient_user_id=peer_trainee_user_id,
            notif_type=notif_type,
            title=title_map[action],
            body=body,
            data=data,
        )
        emit_ids = [peer_trainee_user_id]
        if actor_trainer_user_id:
            emit_ids.append(actor_trainer_user_id)
        self.emit_plan_assignment_changed_sync(
            user_ids=emit_ids,
            action=action,
            plan_id=plan_id,
            plan_title=title_text,
            trainer_user_id=trainer_user_id,
            trainee_user_id=trainee_user_id,
            trainee_profile_id=trainee_profile_id,
            occurred_at=occurred_at,
        )
        return row

    async def _deliver(
        self,
        *,
        recipient_user_id: str,
        notif_type: str,
        title: str,
        body: str,
        data: dict[str, Any],
        skip_remote_if_online: bool,
        high_priority: bool,
    ) -> models.AppNotification | None:
        prefs = self.prefs_for(recipient_user_id)
        flat = flatten_notification_data(data)
        if "type" not in flat:
            flat["type"] = notif_type

        # Inbox: always for chat/chat_call/follow; for other types skip if type pref is off.
        create_inbox = True
        pref_attr = _PUSH_TYPE_PREF.get(notif_type)
        if notif_type not in _INBOX_ALWAYS and pref_attr and not getattr(prefs, pref_attr, True):
            create_inbox = False
            log.info(
                "inbox_skipped_pref_off",
                user_id=recipient_user_id,
                pref=pref_attr,
                type=notif_type,
            )

        row: models.AppNotification | None = None
        if create_inbox:
            row = self.notifications.create(
                user_id=recipient_user_id,
                type=notif_type,
                title=title,
                body=body,
                data=flat,
            )
            out = self._out(row)
            if self.hub is not None:
                try:
                    await self.hub.emit_notification(
                        recipient_user_id, out.model_dump(by_alias=True, mode="json")
                    )
                except Exception:
                    log.exception(
                        "notification_socket_emit_failed",
                        user_id=recipient_user_id,
                        type=notif_type,
                    )

        allow_push = self._should_send_push(prefs, notif_type)
        if not allow_push:
            log.info(
                "push_skipped_pref",
                user_id=recipient_user_id,
                type=notif_type,
                master_push=prefs.push,
                inbox=bool(row),
            )
            return row

        online = self.hub.is_online(recipient_user_id) if self.hub is not None else False
        if skip_remote_if_online and online:
            log.info("push_skipped_online", user_id=recipient_user_id, type=notif_type)
            return row

        tokens = self.tokens.list_for_user(recipient_user_id)
        if not tokens:
            log.info(
                "push_skipped_no_tokens",
                recipient_user_id=recipient_user_id,
                type=notif_type,
                title=title,
            )
            return row

        badge = self.notifications.unread_count(recipient_user_id)
        log.info(
            "push_queued",
            recipient_user_id=recipient_user_id,
            type=notif_type,
            token_count=len(tokens),
            title=title,
            body=body[:80],
            high_priority=high_priority,
            data=flat,
            notification_id=row.id if row else None,
            badge=badge,
        )
        try:
            await self._dispatch_remote(
                tokens=tokens,
                title=title,
                body=body,
                badge=badge,
                data=flat,
                high_priority=high_priority,
            )
        except Exception:
            log.exception(
                "push_dispatch_failed",
                user_id=recipient_user_id,
                type=notif_type,
            )
        return row

    async def _dispatch_remote(
        self,
        *,
        tokens: list[models.DevicePushToken],
        title: str,
        body: str,
        badge: int,
        data: dict[str, str],
        high_priority: bool,
    ) -> None:
        settings = get_settings()
        for row in tokens:
            plat = (row.platform or "ios").lower()
            if plat != "ios":
                log.info("push_skipped_android_unconfigured", token_id=row.id)
                continue
            reason = await send_alert(
                settings,
                device_token=row.token,
                title=title,
                body=body,
                badge=badge,
                data=data,
                high_priority=high_priority,
            )
            if reason is None:
                log.info("apns_sent", token_id=row.id, badge=badge)
                continue
            if reason in _APNS_INVALID_REASONS:
                self.tokens.delete_token(row.user_id, row.token)
                log.info("apns_token_deleted", reason=reason, token_id=row.id)

    def _out(self, row: models.AppNotification) -> AppNotificationOut:
        return AppNotificationOut(
            id=row.id,
            type=row.type,
            title=row.title,
            body=row.body,
            data=flatten_notification_data(dict(row.data or {})),
            read_at=row.read_at,
            created_at=row.created_at,
        )
