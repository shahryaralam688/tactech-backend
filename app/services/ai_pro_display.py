"""UI-facing AI Coach Pro badge / plan labels (self-only). No receipts / PII."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db import models

_ACCESS = frozenset({"active", "grace", "billing_retry"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def plan_display_name(plan: str | None) -> str | None:
    if not plan:
        return None
    key = plan.strip().lower()
    if key in {"ai.pro.monthly", "monthly"} or key.endswith(".monthly"):
        return "Monthly"
    if key in {"ai.pro.yearly", "yearly"} or key.endswith(".yearly") or key.endswith(".annual"):
        return "Yearly"
    # Humanize last segment: ai.pro.foo_bar → Foo bar
    tail = key.split(".")[-1].replace("_", " ").replace("-", " ").strip()
    if not tail:
        return "AI Coach Pro"
    return tail[:1].upper() + tail[1:]


def resolve_display_status(
    row: models.AiEntitlement | None, *, entitled: bool, now: datetime | None = None
) -> str:
    """Map DB row + live entitlement → UI status."""
    now = now or _utcnow()
    if row is None:
        return "inactive"
    raw = (row.status or "").strip().lower() or "inactive"
    ends = _aware(row.ends_at)
    expired_by_time = ends is not None and ends <= now

    if entitled:
        if raw in _ACCESS:
            return raw
        return "active"

    if raw == "revoked":
        return "revoked"
    if raw in {"expired", "inactive"} or expired_by_time:
        return "expired" if (raw == "expired" or expired_by_time) else "inactive"
    if raw in {"grace", "billing_retry"}:
        return raw
    if raw == "active" and expired_by_time:
        return "expired"
    return raw if raw else "inactive"


def will_renew(*, entitled: bool, status: str, source: str | None) -> bool | None:
    if not entitled:
        return False
    src = (source or "").strip().lower()
    if src == "manual":
        return False
    if status in {"active", "grace", "billing_retry"}:
        return True
    return False


def build_ai_display(
    row: models.AiEntitlement | None,
    *,
    entitled: bool,
) -> dict[str, Any]:
    """Shared fields for /me/ai and entitlements.ai."""
    status = resolve_display_status(row, entitled=entitled)
    if not entitled:
        return {
            "active": False,
            "plan": None,
            "plan_display_name": None,
            "badge_label": None,
            "badge_full_label": None,
            "status": status,
            "starts_at": None,
            "ends_at": _aware(row.ends_at) if row else None,
            "renews_at": None,
            "source": None,
            "will_renew": False,
        }

    plan = (row.plan or row.product_id or row.apple_product_id) if row else None
    source = (row.source or "apple") if row else "apple"
    ends = _aware(row.ends_at) if row else None
    renew = will_renew(entitled=True, status=status, source=source)
    return {
        "active": True,
        "plan": plan,
        "plan_display_name": plan_display_name(plan),
        "badge_label": "Pro",
        "badge_full_label": "AI Coach Pro",
        "status": status,
        "starts_at": _aware(row.starts_at) if row else None,
        "ends_at": ends,
        "renews_at": ends if renew else None,
        "source": source,
        "will_renew": renew,
    }
