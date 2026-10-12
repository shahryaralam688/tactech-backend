"""Trainer Boost billing (Phase 2). Webhook / verified session is source of truth.

Activation policy (single active row):
- First paid purchase: startsAt=now, endsAt=now+durationDays, status=active
- While active, another purchase: extend endsAt from current endsAt (not now)
- Idempotent on stripe_checkout_session_id — never double-extend the same session
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from dataclasses import dataclass

from app.core.config import Settings
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.repositories.billing import BillingRepository, extend_or_start_window
from app.repositories.coach_profile import CoachProfileRepository
from app.schemas.billing import (
    BillingProductOut,
    BillingProductPage,
    BoostCheckoutOut,
    BoostCheckoutRequest,
    BoostConfirmRequest,
    BoostHistoryItemOut,
    MeBoostOut,
)
from app.services.billing.local_wallets import (
    EasypaisaBoostProvider,
    JazzCashBoostProvider,
    LocalPaymentResult,
    html_auto_post_form,
)
from app.services.billing.provider import CheckoutSessionResult, PaymentProvider
from app.services.billing.stripe_provider import StripePaymentProvider

if TYPE_CHECKING:
    from app.api.deps import Principal

log = get_logger("tactech.billing")

_LOCAL_PROVIDERS = frozenset({"jazzcash", "easypaisa"})


@dataclass
class PaidBoostPayment:
    """Normalized paid boost — sole input to activate_boost (all providers)."""

    provider: str
    user_id: str
    trainer_id: str
    product_id: str
    amount_minor: int
    currency: str
    provider_payment_id: str
    merchant_txn_id: str | None = None
    stripe_checkout_session_id: str | None = None
    stripe_payment_intent_id: str | None = None
    attempt_id: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def product_providers(product: models.BillingProduct) -> list[str]:
    if product.providers:
        return [str(p) for p in product.providers]
    if product.type == "ai":
        return ["apple"]
    cur = (product.currency or "usd").lower()
    if cur == "pkr":
        return ["jazzcash", "easypaisa"]
    return ["stripe"]


def _checkout_from_object(obj: Any) -> CheckoutSessionResult:
    if isinstance(obj, dict):
        meta = {str(k): str(v) for k, v in (obj.get("metadata") or {}).items()}
        pi = obj.get("payment_intent")
        return CheckoutSessionResult(
            session_id=obj["id"],
            url=obj.get("url") or "",
            payment_intent_id=str(pi) if pi else None,
            amount_total=obj.get("amount_total"),
            currency=obj.get("currency"),
            payment_status=obj.get("payment_status"),
            status=obj.get("status"),
            metadata=meta,
            raw=obj,
        )
    meta_raw = getattr(obj, "metadata", None) or {}
    meta = {str(k): str(v) for k, v in dict(meta_raw).items()}
    pi = getattr(obj, "payment_intent", None)
    if hasattr(pi, "id"):
        pi = pi.id
    return CheckoutSessionResult(
        session_id=obj.id,
        url=getattr(obj, "url", None) or "",
        payment_intent_id=str(pi) if pi else None,
        amount_total=getattr(obj, "amount_total", None),
        currency=getattr(obj, "currency", None),
        payment_status=getattr(obj, "payment_status", None),
        status=getattr(obj, "status", None),
        metadata=meta,
        raw=obj,
    )


class BillingService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        provider: PaymentProvider | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.repo = BillingRepository(db)
        self.profiles = CoachProfileRepository(db)
        self._provider = provider

    def _stripe(self) -> PaymentProvider:
        if self._provider is not None:
            return self._provider
        return StripePaymentProvider(self.settings)

    def list_products(
        self, *, type: str | None = "boost", currency: str | None = None
    ) -> BillingProductPage:
        rows = self.repo.list_products(type=type, active_only=True, currency=currency)
        return BillingProductPage(
            items=[
                BillingProductOut(
                    id=r.id,
                    type=r.type,
                    name=r.name,
                    description=r.description or "",
                    duration_days=r.duration_days,
                    tier=r.tier if r.type == "boost" else None,
                    amount_minor=r.amount_minor,
                    currency=r.currency,
                    active=r.active,
                    apple_product_id=r.apple_product_id,
                    billing_period=r.billing_period,
                    providers=product_providers(r),
                )
                for r in rows
            ]
        )

    def get_me_boost(self, principal: Principal) -> MeBoostOut:
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")
        self.repo.expire_stale()
        active = self.repo.active_boost_for_user(principal.user_id)
        history = [
            BoostHistoryItemOut(
                id=b.id,
                product_id=b.product_id,
                tier=b.tier,
                status=b.status,
                starts_at=b.starts_at,
                ends_at=b.ends_at,
                amount_minor=b.amount_minor,
                currency=b.currency,
                created_at=b.created_at,
            )
            for b in self.repo.list_boosts_for_user(principal.user_id, limit=10)
        ]
        if active is None:
            return MeBoostOut(active=False, history=history)
        return MeBoostOut(
            active=True,
            tier=active.tier,
            starts_at=active.starts_at,
            ends_at=active.ends_at,
            source=active.source or "stripe",
            product_id=active.product_id,
            history=history,
        )

    def create_boost_checkout(
        self, principal: Principal, payload: BoostCheckoutRequest
    ) -> BoostCheckoutOut:
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")

        product = self.repo.get_product(payload.product_id)
        if product is None or product.type != "boost" or not product.active:
            raise NotFoundError("Boost product not found.")

        allowed = product_providers(product)
        provider = (payload.provider or "").strip().lower()
        if not provider:
            if (product.currency or "").lower() == "usd" and "stripe" in allowed:
                provider = "stripe"
            else:
                raise ValidationAppError(
                    "Choose a payment provider (jazzcash or easypaisa).",
                    fields={"provider": "required"},
                )
        if provider not in allowed:
            raise ValidationAppError(
                f"Provider '{provider}' is not available for this product.",
                fields={"provider": "unsupported"},
            )

        warning = None
        profile = self.profiles.get_by_trainer_id(principal.trainer_id)
        if profile is None or not profile.is_public:
            warning = "Publish your public profile so trainees can see your boost."

        if provider == "stripe":
            return self._checkout_stripe(principal, product, payload, warning=warning)
        return self._checkout_local(principal, product, provider, payload, warning=warning)

    def _checkout_stripe(
        self,
        principal: Principal,
        product: models.BillingProduct,
        payload: BoostCheckoutRequest,
        *,
        warning: str | None,
    ) -> BoostCheckoutOut:
        if not product.stripe_price_id:
            raise ValidationAppError(
                "This boost product is not available for Stripe checkout yet.",
                fields={"productId": "missing_price"},
            )
        success_url = (payload.success_url or self.settings.stripe_success_url or "").strip()
        cancel_url = (payload.cancel_url or self.settings.stripe_cancel_url or "").strip()
        if not success_url or not cancel_url:
            raise ValidationAppError(
                "Checkout URLs are not configured. Set STRIPE_SUCCESS_URL and STRIPE_CANCEL_URL.",
                fields={"stripe": "urls_missing"},
            )
        metadata = {
            "userId": principal.user_id,
            "trainerId": principal.trainer_id or "",
            "productId": product.id,
            "purpose": "coach_boost",
        }
        session = self._stripe().create_checkout_session(
            price_id=product.stripe_price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=principal.user_id,
            metadata=metadata,
        )
        if not session.url:
            raise ValidationAppError("Stripe did not return a checkout URL.")

        merchant_txn = f"stripe_{session.session_id}"
        attempt = self.repo.create_attempt(
            user_id=principal.user_id,
            trainer_id=principal.trainer_id or "",
            product=product,
            provider="stripe",
            merchant_txn_id=merchant_txn,
            redirect_url=session.url,
            stripe_checkout_session_id=session.session_id,
        )
        if self.repo.get_boost_by_checkout_session(session.session_id) is None:
            self.repo.create_pending_boost(
                user_id=principal.user_id,
                trainer_id=principal.trainer_id or "",
                product=product,
                checkout_session_id=session.session_id,
                provider="stripe",
                merchant_txn_id=merchant_txn,
            )
        log.info(
            "boost_checkout_created",
            provider="stripe",
            attempt_id=attempt.id,
            checkout_session_id=session.session_id,
            product_id=product.id,
        )
        return BoostCheckoutOut(
            checkout_session_id=session.session_id,
            attempt_id=attempt.id,
            provider="stripe",
            url=session.url,
            publishable_key=self.settings.stripe_publishable_key or None,
            warning=warning,
        )

    def _checkout_local(
        self,
        principal: Principal,
        product: models.BillingProduct,
        provider: str,
        payload: BoostCheckoutRequest,
        *,
        warning: str | None,
    ) -> BoostCheckoutOut:
        if (product.currency or "").lower() != "pkr":
            raise ValidationAppError("Local wallets require a PKR boost product.")

        attempt_id = str(uuid4())
        merchant_txn_id = f"TCT{uuid4().hex[:16].upper()}"
        public_base = (self.settings.public_base_url or "").rstrip("/")
        if not public_base:
            # Fallback so pay page path is absolute when iOS uses ngrok URL from client successUrl host
            public_base = "http://127.0.0.1:8000"

        success = (payload.success_url or self.settings.boost_success_url or "").replace(
            "{ATTEMPT_ID}", attempt_id
        )
        return_url = success or self.settings.jazzcash_return_url

        if provider == "jazzcash":
            built = JazzCashBoostProvider(self.settings).build_checkout(
                attempt_id=attempt_id,
                merchant_txn_id=merchant_txn_id,
                amount_minor=product.amount_minor,
                description=product.name,
                return_url=return_url,
                public_pay_base=public_base,
            )
        else:
            built = EasypaisaBoostProvider(self.settings).build_checkout(
                attempt_id=attempt_id,
                merchant_txn_id=merchant_txn_id,
                amount_minor=product.amount_minor,
                description=product.name,
                return_url=return_url,
                public_pay_base=public_base,
            )

        # Persist attempt with pre-assigned id
        now = _utcnow()
        attempt = models.BoostCheckoutAttempt(
            id=attempt_id,
            user_id=principal.user_id,
            trainer_id=principal.trainer_id or "",
            product_id=product.id,
            provider=provider,
            status="redirected",
            amount_minor=product.amount_minor,
            currency=product.currency,
            merchant_txn_id=merchant_txn_id,
            redirect_url=built.url,
            provider_payload={
                "formFields": built.form_fields,
                "providerCheckoutUrl": built.provider_checkout_url,
            },
            created_at=now,
            updated_at=now,
        )
        self.db.add(attempt)
        self.db.commit()

        self.repo.create_pending_boost(
            user_id=principal.user_id,
            trainer_id=principal.trainer_id or "",
            product=product,
            provider=provider,
            merchant_txn_id=merchant_txn_id,
        )
        log.info(
            "boost_checkout_created",
            provider=provider,
            attempt_id=attempt_id,
            merchant_txn_id=merchant_txn_id,
            product_id=product.id,
        )
        return BoostCheckoutOut(
            checkout_session_id=None,
            attempt_id=attempt_id,
            provider=provider,
            url=built.url,
            publishable_key=None,
            warning=warning,
        )

    def pay_page_html(self, attempt_id: str) -> str:
        """Auto-POST HTML form to JazzCash/Easypaisa hosted checkout."""
        attempt = self.repo.get_attempt(attempt_id)
        if attempt is None or attempt.status in {"expired", "failed"}:
            raise NotFoundError("Checkout attempt not found.")
        payload = attempt.provider_payload or {}
        fields = payload.get("formFields") or {}
        action = payload.get("providerCheckoutUrl") or ""
        if not fields or not action:
            raise ValidationAppError("Checkout form is not ready.")
        return html_auto_post_form(
            action=action,
            fields={str(k): str(v) for k, v in fields.items()},
            title=f"Pay with {attempt.provider}",
        )

    def confirm_boost_checkout(
        self, principal: Principal, payload: BoostConfirmRequest
    ) -> MeBoostOut:
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")

        if payload.checkout_session_id:
            session = self._stripe().retrieve_checkout_session(payload.checkout_session_id)
            meta = session.metadata or {}
            if meta.get("userId") and meta["userId"] != principal.user_id:
                raise ForbiddenError("This checkout does not belong to you.")
            paid = (session.payment_status or "") == "paid" or (session.status or "") == "complete"
            if paid:
                self.activate_from_checkout_session(session)
            return self.get_me_boost(principal)

        if payload.attempt_id:
            attempt = self.repo.get_attempt(payload.attempt_id)
            if attempt is None or attempt.user_id != principal.user_id:
                raise NotFoundError("Checkout attempt not found.")
            if attempt.status == "paid":
                return self.get_me_boost(principal)
            if attempt.provider == "stripe" and attempt.stripe_checkout_session_id:
                return self.confirm_boost_checkout(
                    principal,
                    BoostConfirmRequest(checkout_session_id=attempt.stripe_checkout_session_id),
                )
            # Local wallets: IPN is source of truth; confirm is a no-op refresh unless already paid
            return self.get_me_boost(principal)

        raise ValidationAppError(
            "Provide checkoutSessionId or attemptId.",
            fields={"checkoutSessionId": "required"},
        )

    def activate_boost(self, payment: PaidBoostPayment) -> models.CoachBoost:
        """Single activation path for Stripe + JazzCash + Easypaisa (idempotent)."""
        # Idempotency: same provider payment id already activated
        existing_paid = self.repo.get_boost_by_provider_payment(
            payment.provider, payment.provider_payment_id
        )
        if existing_paid is not None and existing_paid.status == "active" and existing_paid.starts_at:
            log.info(
                "boost_activate_idempotent",
                provider=payment.provider,
                provider_payment_id=payment.provider_payment_id,
                boost_id=existing_paid.id,
            )
            return existing_paid

        if payment.stripe_checkout_session_id:
            by_session = self.repo.get_boost_by_checkout_session(payment.stripe_checkout_session_id)
            if by_session is not None and by_session.status == "active" and by_session.starts_at:
                return by_session

        product = self.repo.get_product(payment.product_id)
        if product is None:
            raise NotFoundError("Boost product not found.")
        days = int(product.duration_days or 7)

        now = _utcnow()
        active = self.repo.active_boost_for_user(payment.user_id, now=now)
        starts, ends = extend_or_start_window(existing=active, duration_days=days, now=now)

        pending = None
        if payment.merchant_txn_id:
            pending = self.repo.get_boost_by_merchant_txn(payment.merchant_txn_id)
        if pending is None and payment.stripe_checkout_session_id:
            pending = self.repo.get_boost_by_checkout_session(payment.stripe_checkout_session_id)

        if active is not None:
            if pending is not None and pending.id != active.id:
                pending.status = "canceled"
                pending.stripe_checkout_session_id = None
                pending.provider_payment_id = None
                # Release unique merchant_txn / payment refs before active row takes them
                pending.merchant_txn_id = None
                pending.updated_at = now
                self.db.add(pending)
                self.db.flush()

            active.ends_at = ends
            active.tier = product.tier
            active.product_id = product.id
            active.status = "active"
            active.source = payment.provider
            active.provider = payment.provider
            active.provider_payment_id = payment.provider_payment_id
            active.merchant_txn_id = payment.merchant_txn_id
            active.amount_minor = payment.amount_minor
            active.currency = payment.currency
            active.payment_ref = payment.provider_payment_id
            if payment.stripe_checkout_session_id:
                active.stripe_checkout_session_id = payment.stripe_checkout_session_id
            if payment.stripe_payment_intent_id:
                active.stripe_payment_intent_id = payment.stripe_payment_intent_id
            saved = self.repo.save_boost(active)
            self._mark_attempt_paid(payment)
            log.info(
                "boost_extended",
                provider=payment.provider,
                boost_id=saved.id,
                user_id=payment.user_id,
                ends_at=saved.ends_at.isoformat() if saved.ends_at else None,
            )
            return saved

        row = pending
        if row is None:
            row = models.CoachBoost(
                id=str(uuid4()),
                user_id=payment.user_id,
                trainer_id=payment.trainer_id,
                product_id=product.id,
                tier=product.tier,
                status="pending",
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)

        row.trainer_id = payment.trainer_id
        row.product_id = product.id
        row.tier = product.tier
        row.status = "active"
        row.starts_at = starts
        row.ends_at = ends
        row.amount_minor = payment.amount_minor
        row.currency = payment.currency
        row.source = payment.provider
        row.provider = payment.provider
        row.provider_payment_id = payment.provider_payment_id
        row.merchant_txn_id = payment.merchant_txn_id
        row.payment_ref = payment.provider_payment_id
        if payment.stripe_checkout_session_id:
            row.stripe_checkout_session_id = payment.stripe_checkout_session_id
        if payment.stripe_payment_intent_id:
            row.stripe_payment_intent_id = payment.stripe_payment_intent_id
        saved = self.repo.save_boost(row)
        self._mark_attempt_paid(payment)
        log.info(
            "boost_activated",
            provider=payment.provider,
            boost_id=saved.id,
            user_id=payment.user_id,
            starts_at=saved.starts_at.isoformat() if saved.starts_at else None,
            ends_at=saved.ends_at.isoformat() if saved.ends_at else None,
        )
        return saved

    def _mark_attempt_paid(self, payment: PaidBoostPayment) -> None:
        attempt = None
        if payment.attempt_id:
            attempt = self.repo.get_attempt(payment.attempt_id)
        if attempt is None and payment.merchant_txn_id:
            attempt = self.repo.get_attempt_by_merchant_txn(payment.merchant_txn_id)
        if attempt is None and payment.stripe_checkout_session_id:
            attempt = self.db.scalars(
                select(models.BoostCheckoutAttempt).where(
                    models.BoostCheckoutAttempt.stripe_checkout_session_id
                    == payment.stripe_checkout_session_id
                )
            ).first()
        if attempt is None:
            return
        attempt.status = "paid"
        attempt.provider_payment_id = payment.provider_payment_id
        attempt.paid_at = _utcnow()
        self.repo.save_attempt(attempt)

    def activate_from_checkout_session(self, session: CheckoutSessionResult) -> models.CoachBoost:
        meta = session.metadata or {}
        user_id = meta.get("userId")
        if not user_id and session.raw is not None:
            if isinstance(session.raw, dict):
                user_id = session.raw.get("client_reference_id")
            else:
                user_id = getattr(session.raw, "client_reference_id", None)
        trainer_id = meta.get("trainerId")
        product_id = meta.get("productId")
        if not user_id or not product_id:
            raise ValidationAppError("Checkout metadata missing userId/productId.")
        if not trainer_id:
            trainer = self.db.scalars(
                select(models.TrainerProfile).where(models.TrainerProfile.user_id == user_id)
            ).first()
            trainer_id = trainer.id if trainer else None
        if not trainer_id:
            raise ValidationAppError("Trainer profile missing for boost activation.")
        product = self.repo.get_product(product_id)
        amount = session.amount_total if session.amount_total is not None else (
            product.amount_minor if product else 0
        )
        currency = (session.currency or (product.currency if product else "usd") or "usd").lower()
        return self.activate_boost(
            PaidBoostPayment(
                provider="stripe",
                user_id=user_id,
                trainer_id=trainer_id,
                product_id=product_id,
                amount_minor=int(amount),
                currency=currency,
                provider_payment_id=session.payment_intent_id or session.session_id,
                merchant_txn_id=f"stripe_{session.session_id}",
                stripe_checkout_session_id=session.session_id,
                stripe_payment_intent_id=session.payment_intent_id,
            )
        )

    def apply_local_payment(self, result: LocalPaymentResult) -> models.CoachBoost | None:
        """Activate from verified JazzCash/Easypaisa IPN."""
        event_id = f"{result.provider}:{result.provider_payment_id}"
        if not self.repo.try_record_event(
            provider=result.provider,
            event_id=event_id,
            event_type="ipn_paid" if result.paid else "ipn_failed",
            payload=result.raw,
        ):
            log.info("local_ipn_duplicate", provider=result.provider, event_id=event_id)
            return self.repo.get_boost_by_provider_payment(
                result.provider, result.provider_payment_id
            )

        attempt = self.repo.get_attempt_by_merchant_txn(result.merchant_txn_id)
        if attempt is None:
            log.warning("local_ipn_unknown_txn", merchant_txn_id=result.merchant_txn_id)
            return None

        if not result.paid:
            attempt.status = "failed"
            self.repo.save_attempt(attempt)
            return None

        if result.amount_minor is not None and result.amount_minor != attempt.amount_minor:
            raise ValidationAppError(
                "Payment amount does not match checkout.",
                fields={"amount": "mismatch"},
            )

        return self.activate_boost(
            PaidBoostPayment(
                provider=result.provider,
                user_id=attempt.user_id,
                trainer_id=attempt.trainer_id,
                product_id=attempt.product_id or "",
                amount_minor=attempt.amount_minor,
                currency=attempt.currency,
                provider_payment_id=result.provider_payment_id,
                merchant_txn_id=result.merchant_txn_id,
                attempt_id=attempt.id,
            )
        )

    def handle_jazzcash_ipn(self, form: dict) -> dict:
        result = JazzCashBoostProvider(self.settings).verify_ipn(form)
        self.apply_local_payment(result)
        # JazzCash often expects plain success body
        return {"received": True, "status": "OK"}

    def handle_easypaisa_ipn(self, form: dict) -> dict:
        result = EasypaisaBoostProvider(self.settings).verify_ipn(form)
        self.apply_local_payment(result)
        return {"received": True, "status": "OK"}

    def grant_manual_boost(
        self,
        *,
        user_id: str,
        trainer_id: str,
        product_id: str = "boost.featured.7d",
        duration_days: int | None = None,
    ) -> models.CoachBoost:
        product = self.repo.get_product(product_id)
        days = duration_days or (product.duration_days if product else 7)
        tier = product.tier if product else "featured"
        now = _utcnow()
        active = self.repo.active_boost_for_user(user_id, now=now)
        starts, ends = extend_or_start_window(existing=active, duration_days=days, now=now)
        if active is not None:
            active.ends_at = ends
            active.status = "active"
            active.source = "manual"
            active.tier = tier
            if product:
                active.product_id = product.id
            return self.repo.save_boost(active)

        row = models.CoachBoost(
            id=str(uuid4()),
            user_id=user_id,
            trainer_id=trainer_id,
            product_id=product.id if product else None,
            tier=tier,
            status="active",
            starts_at=starts,
            ends_at=ends,
            amount_minor=product.amount_minor if product else 0,
            currency=product.currency if product else "usd",
            source="manual",
            payment_ref=f"manual:{uuid4().hex[:12]}",
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        log.info("boost_granted_manual", boost_id=row.id, user_id=user_id, ends_at=row.ends_at)
        return row

    def handle_stripe_webhook(self, payload: bytes, signature_header: str | None) -> dict:
        event = self._stripe().construct_webhook_event(payload, signature_header)
        event_id = event["id"] if isinstance(event, dict) else event.id
        event_type = event["type"] if isinstance(event, dict) else event.type
        data_object = event["data"]["object"] if isinstance(event, dict) else event.data.object

        try:
            payload_dict: dict[str, Any] = (
                dict(event) if isinstance(event, dict) else {"id": event_id, "type": event_type}
            )
        except Exception:
            payload_dict = {"id": event_id, "type": event_type}

        inserted = self.repo.try_record_event(
            provider="stripe",
            event_id=event_id,
            event_type=event_type,
            payload=payload_dict,
        )
        if not inserted:
            log.info("stripe_webhook_duplicate", event_id=event_id, type=event_type)
            return {"received": True}

        log.info("stripe_webhook_received", event_id=event_id, type=event_type)

        if event_type == "checkout.session.completed":
            session = _checkout_from_object(data_object)
            self.activate_from_checkout_session(session)
        elif event_type == "checkout.session.expired":
            sid = (
                data_object.get("id")
                if isinstance(data_object, dict)
                else getattr(data_object, "id", None)
            )
            if sid:
                pending = self.repo.get_boost_by_checkout_session(str(sid))
                if pending is not None and pending.status == "pending":
                    pending.status = "canceled"
                    self.repo.save_boost(pending)
        elif event_type in {"charge.refunded", "charge.refund.updated"}:
            self._handle_refund(data_object)

        return {"received": True}

    def _handle_refund(self, charge_obj: Any) -> None:
        """Refund ends boost immediately: status=refunded, endsAt=now."""
        if isinstance(charge_obj, dict):
            pi = charge_obj.get("payment_intent")
        else:
            pi = getattr(charge_obj, "payment_intent", None)
        if not pi:
            return
        pi_id = pi if isinstance(pi, str) else getattr(pi, "id", None)
        if not pi_id:
            return
        boost = self.db.scalars(
            select(models.CoachBoost).where(models.CoachBoost.stripe_payment_intent_id == str(pi_id))
        ).first()
        if boost is None:
            return
        now = _utcnow()
        boost.status = "refunded"
        boost.ends_at = now
        self.repo.save_boost(boost)
        log.info("boost_refunded", boost_id=boost.id, payment_intent_id=pi_id)

    def expire_stale(self) -> int:
        n = self.repo.expire_stale()
        if n:
            log.info("boosts_expired", count=n)
        return n
