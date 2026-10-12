"""Billing / Boost DTOs (Phase 2). camelCase via APIModel."""

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class BillingProductOut(APIModel):
    id: str
    type: str
    name: str
    description: str = ""
    duration_days: int | None = None
    tier: str | None = None
    amount_minor: int
    currency: str
    active: bool = True
    apple_product_id: str | None = None
    billing_period: str | None = None
    providers: list[str] = Field(default_factory=list)


class BillingProductPage(APIModel):
    items: list[BillingProductOut]


class MeAiOut(APIModel):
    active: bool = False
    plan: str | None = None
    plan_display_name: str | None = None
    badge_label: str | None = None
    badge_full_label: str | None = None
    status: str = "inactive"  # inactive|active|grace|expired|revoked|billing_retry
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    renews_at: datetime | None = None
    source: str | None = None
    will_renew: bool | None = False
    free_tease_remaining: int = 0
    free_tease_limit: int = 0


class AppleVerifyRequest(APIModel):
    signed_transaction: str | None = Field(default=None, max_length=200_000)
    signed_renewal_info: str | None = Field(default=None, max_length=200_000)
    transaction_id: str | None = Field(default=None, max_length=128)
    original_transaction_id: str | None = Field(default=None, max_length=128)


class AppleRestoreTransaction(APIModel):
    signed_transaction: str | None = Field(default=None, max_length=200_000)
    transaction_id: str | None = Field(default=None, max_length=128)
    original_transaction_id: str | None = Field(default=None, max_length=128)


class AppleRestoreRequest(APIModel):
    transactions: list[AppleRestoreTransaction] = Field(default_factory=list)


class AppleWebhookAck(APIModel):
    received: bool = True


class BoostCheckoutRequest(APIModel):
    product_id: str = Field(min_length=1, max_length=64)
    provider: str | None = Field(default=None, max_length=32)  # stripe | jazzcash | easypaisa
    success_url: str | None = Field(default=None, max_length=1024)
    cancel_url: str | None = Field(default=None, max_length=1024)


class BoostCheckoutOut(APIModel):
    checkout_session_id: str | None = None
    attempt_id: str | None = None
    provider: str = "stripe"
    url: str
    publishable_key: str | None = None
    warning: str | None = None


class BoostConfirmRequest(APIModel):
    checkout_session_id: str | None = Field(default=None, max_length=255)
    attempt_id: str | None = Field(default=None, max_length=64)
    provider: str | None = Field(default=None, max_length=32)


class LocalWebhookAck(APIModel):
    received: bool = True
    status: str | None = None


class BoostHistoryItemOut(APIModel):
    id: str
    product_id: str | None = None
    tier: str | None = None
    status: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    amount_minor: int | None = None
    currency: str | None = None
    created_at: datetime


class MeBoostOut(APIModel):
    active: bool = False
    tier: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    source: str | None = None
    product_id: str | None = None
    history: list[BoostHistoryItemOut] = Field(default_factory=list)


class StripeWebhookAck(APIModel):
    received: bool = True


class GrantBoostRequest(APIModel):
    """Dev/QA complimentary boost (manual source)."""

    user_id: str | None = Field(default=None, max_length=64)
    trainer_id: str | None = Field(default=None, max_length=64)
    product_id: str = Field(default="boost.featured.7d", max_length=64)
    duration_days: int | None = Field(default=None, ge=1, le=365)
