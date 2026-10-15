"""Shared AI entitlement + freemium quota gate — used by all AI generate routes."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AiQuotaExceededError, AiRequiredError
from app.core.logging import get_logger
from app.db import models

log = get_logger("tactech.ai_access")

_ACCESS_STATUSES = frozenset({"active", "grace", "billing_retry"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_week_start(now: datetime | None = None) -> date:
    now = now or _utcnow()
    d = now.date()
    return d - timedelta(days=d.weekday())  # Monday


class AiAccessService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def get_entitlement_row(self, user_id: str) -> models.AiEntitlement | None:
        return self.db.scalars(
            select(models.AiEntitlement).where(models.AiEntitlement.user_id == user_id)
        ).first()

    def is_entitlement_active(self, user_id: str, *, now: datetime | None = None) -> bool:
        now = now or _utcnow()
        row = self.get_entitlement_row(user_id)
        if row is None:
            return False
        if row.status not in _ACCESS_STATUSES:
            return False
        if row.ends_at is not None:
            ends = row.ends_at
            if ends.tzinfo is None:
                ends = ends.replace(tzinfo=timezone.utc)
            if ends <= now:
                return False
        return True

    def free_tease_limit(self) -> int:
        return max(0, int(self.settings.ai_free_tease_messages_per_week or 0))

    def free_chat_daily_limit(self) -> int:
        return max(0, int(self.settings.ai_free_chat_daily_limit or 0))

    def free_plan_generations_limit(self) -> int:
        return max(0, int(self.settings.ai_free_plan_generations or 0))

    def free_tease_used(self, user_id: str, *, now: datetime | None = None) -> int:
        week = iso_week_start(now)
        row = self.db.scalars(
            select(models.AiUsageWeekly).where(
                models.AiUsageWeekly.user_id == user_id,
                models.AiUsageWeekly.week_start == week,
            )
        ).first()
        return int(row.message_count) if row else 0

    def free_tease_remaining(self, user_id: str, *, now: datetime | None = None) -> int:
        limit = self.free_tease_limit()
        if limit <= 0:
            return 0
        return max(0, limit - self.free_tease_used(user_id, now=now))

    def free_chat_daily_used(self, user_id: str, *, now: datetime | None = None) -> int:
        day = (now or _utcnow()).date()
        row = self.db.scalars(
            select(models.AiUsageDaily).where(
                models.AiUsageDaily.user_id == user_id,
                models.AiUsageDaily.usage_day == day,
            )
        ).first()
        return int(row.message_count) if row else 0

    def free_chat_daily_remaining(self, user_id: str, *, now: datetime | None = None) -> int:
        limit = self.free_chat_daily_limit()
        if limit <= 0:
            return 0
        return max(0, limit - self.free_chat_daily_used(user_id, now=now))

    def consume_tease(self, user_id: str, *, now: datetime | None = None) -> None:
        week = iso_week_start(now)
        row = self.db.scalars(
            select(models.AiUsageWeekly).where(
                models.AiUsageWeekly.user_id == user_id,
                models.AiUsageWeekly.week_start == week,
            )
        ).first()
        if row is None:
            row = models.AiUsageWeekly(
                id=str(uuid4()),
                user_id=user_id,
                week_start=week,
                message_count=1,
            )
            self.db.add(row)
        else:
            row.message_count = int(row.message_count) + 1
            self.db.add(row)
        self.db.commit()

    def consume_daily_chat(self, user_id: str, *, now: datetime | None = None) -> None:
        day = (now or _utcnow()).date()
        row = self.db.scalars(
            select(models.AiUsageDaily).where(
                models.AiUsageDaily.user_id == user_id,
                models.AiUsageDaily.usage_day == day,
            )
        ).first()
        if row is None:
            row = models.AiUsageDaily(
                id=str(uuid4()),
                user_id=user_id,
                usage_day=day,
                message_count=1,
            )
            self.db.add(row)
        else:
            row.message_count = int(row.message_count) + 1
            self.db.add(row)
        self.db.commit()

    def plan_generations_used(self, user_id: str) -> int:
        row = self.db.get(models.AiPlanGenerationUsage, user_id)
        return int(row.generation_count) if row else 0

    def plan_generations_remaining(self, user_id: str) -> int:
        if self.is_entitlement_active(user_id):
            return 999  # Pro/Advanced: unlimited regenerate
        limit = self.free_plan_generations_limit()
        if limit <= 0:
            return 0
        return max(0, limit - self.plan_generations_used(user_id))

    def consume_plan_generation(self, user_id: str) -> None:
        if self.is_entitlement_active(user_id):
            return
        row = self.db.get(models.AiPlanGenerationUsage, user_id)
        now = _utcnow()
        if row is None:
            row = models.AiPlanGenerationUsage(
                user_id=user_id,
                generation_count=1,
                updated_at=now,
            )
            self.db.add(row)
        else:
            row.generation_count = int(row.generation_count) + 1
            row.updated_at = now
            self.db.add(row)
        self.db.commit()

    def assert_ai_access(self, user_id: str, *, consume_tease: bool = True) -> None:
        """Allow if subscribed, or free daily/weekly quota remains.

        - Daily free chat (AI_FREE_CHAT_DAILY_LIMIT) preferred for freemium.
        - Weekly tease (AI_FREE_TEASE_MESSAGES_PER_WEEK) still supported.
        - Exhausted free with daily limit > 0 → 402 AI_QUOTA_EXCEEDED.
        - Hard paywall (daily=0 and tease=0) → 402 AI_REQUIRED.
        """
        if self.is_entitlement_active(user_id):
            return

        hint = (getattr(self.settings, "ai_product_hint", None) or "ai.pro.monthly").strip()

        daily_remaining = self.free_chat_daily_remaining(user_id)
        if daily_remaining > 0:
            if consume_tease:
                self.consume_daily_chat(user_id)
                log.info(
                    "ai_free_daily_consumed",
                    user_id=user_id,
                    remaining_after=daily_remaining - 1,
                )
            return

        weekly_remaining = self.free_tease_remaining(user_id)
        if weekly_remaining > 0:
            if consume_tease:
                self.consume_tease(user_id)
                log.info(
                    "ai_free_tease_consumed",
                    user_id=user_id,
                    remaining_after=weekly_remaining - 1,
                )
            return

        if self.free_chat_daily_limit() > 0:
            raise AiQuotaExceededError(
                f"Daily free AI chat limit ({self.free_chat_daily_limit()}) reached. Upgrade to continue.",
                product_hint=hint or "ai.pro.monthly",
                quota="chat",
            )

        raise AiRequiredError(product_hint=hint or "ai.pro.monthly")

    def assert_plan_generate_access(self, user_id: str) -> None:
        """Pro/Advanced: unlimited. Free: AI_FREE_PLAN_GENERATIONS lifetime (default 1)."""
        if self.is_entitlement_active(user_id):
            return
        remaining = self.plan_generations_remaining(user_id)
        if remaining > 0:
            return
        hint = (getattr(self.settings, "ai_product_hint", None) or "ai.pro.monthly").strip()
        limit = self.free_plan_generations_limit()
        raise AiQuotaExceededError(
            f"Free plan generation limit ({limit}) used. Upgrade to regenerate.",
            product_hint=hint or "ai.pro.monthly",
            quota="planGenerate",
        )
