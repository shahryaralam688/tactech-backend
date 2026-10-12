from __future__ import annotations

from typing import Any

import stripe

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.core.logging import get_logger
from app.services.billing.provider import CheckoutSessionResult

log = get_logger("tactech.billing.stripe")


class StripePaymentProvider:
    name = "stripe"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not settings.stripe_secret_key:
            raise ValidationAppError(
                "Stripe is not configured. Set STRIPE_SECRET_KEY.",
                fields={"stripe": "missing"},
            )
        stripe.api_key = settings.stripe_secret_key

    def create_checkout_session(
        self,
        *,
        price_id: str,
        success_url: str,
        cancel_url: str,
        client_reference_id: str,
        metadata: dict[str, str],
    ) -> CheckoutSessionResult:
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=client_reference_id,
                metadata=metadata,
            )
        except stripe.StripeError as exc:
            log.exception("stripe_checkout_create_failed", error=str(exc)[:240])
            raise ValidationAppError(
                "Could not start checkout. Try again shortly.",
                fields={"stripe": "create_failed"},
            ) from exc
        return self._to_result(session)

    def retrieve_checkout_session(self, session_id: str) -> CheckoutSessionResult:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.StripeError as exc:
            log.exception("stripe_checkout_retrieve_failed", session_id=session_id)
            raise ValidationAppError(
                "Checkout session not found.",
                fields={"checkoutSessionId": "invalid"},
            ) from exc
        return self._to_result(session)

    def construct_webhook_event(self, payload: bytes, signature_header: str | None) -> Any:
        secret = self.settings.stripe_webhook_secret
        if not secret:
            raise ValidationAppError(
                "Stripe webhook is not configured.",
                fields={"stripe": "webhook_missing"},
            )
        if not signature_header:
            raise ValidationAppError(
                "Missing Stripe signature.",
                fields={"stripe": "signature_missing"},
            )
        try:
            return stripe.Webhook.construct_event(payload, signature_header, secret)
        except (ValueError, stripe.SignatureVerificationError) as exc:
            log.warning("stripe_webhook_signature_failed", error=str(exc)[:200])
            raise ValidationAppError(
                "Invalid Stripe webhook signature.",
                fields={"stripe": "bad_signature"},
            ) from exc

    def _to_result(self, session: Any) -> CheckoutSessionResult:
        meta = dict(getattr(session, "metadata", None) or {})
        pi = getattr(session, "payment_intent", None)
        if hasattr(pi, "id"):
            pi = pi.id
        return CheckoutSessionResult(
            session_id=session.id,
            url=getattr(session, "url", None) or "",
            payment_intent_id=str(pi) if pi else None,
            amount_total=getattr(session, "amount_total", None),
            currency=getattr(session, "currency", None),
            payment_status=getattr(session, "payment_status", None),
            status=getattr(session, "status", None),
            metadata={str(k): str(v) for k, v in meta.items()},
            raw=session,
        )
