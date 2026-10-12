"""Payment provider interface — Stripe now; JazzCash / Easypaisa later (Phase 2b)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class CheckoutSessionResult:
    session_id: str
    url: str
    payment_intent_id: str | None = None
    amount_total: int | None = None
    currency: str | None = None
    payment_status: str | None = None
    status: str | None = None
    metadata: dict[str, str] | None = None
    raw: Any = None


class PaymentProvider(Protocol):
    """Pluggable checkout + webhook verifier. Phase 2: Stripe only."""

    name: str

    def create_checkout_session(
        self,
        *,
        price_id: str,
        success_url: str,
        cancel_url: str,
        client_reference_id: str,
        metadata: dict[str, str],
    ) -> CheckoutSessionResult: ...

    def retrieve_checkout_session(self, session_id: str) -> CheckoutSessionResult: ...

    def construct_webhook_event(self, payload: bytes, signature_header: str | None) -> Any: ...
