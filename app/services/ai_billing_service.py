"""Trainee AI subscription (Apple IAP) — verify, restore, ASSN V2."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.repositories.billing import BillingRepository
from app.schemas.billing import MeAiOut
from app.services.ai_access import AiAccessService
from app.services.billing.apple_iap import (
    AppleIAPClient,
    VerifiedAppleTransaction,
    decode_jws_payload,
    transaction_from_payload,
)

if TYPE_CHECKING:
    from app.api.deps import Principal

log = get_logger("tactech.ai_billing")

_ACCESS_STATUSES = frozenset({"active", "grace", "billing_retry"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AiBillingService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        apple: AppleIAPClient | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.repo = BillingRepository(db)
        self.access = AiAccessService(db, settings)
        self.apple = apple or AppleIAPClient(settings)

    def get_me_ai(self, user_id: str) -> MeAiOut:
        from app.services.ai_pro_display import build_ai_display

        row = self.access.get_entitlement_row(user_id)
        active = self.access.is_entitlement_active(user_id)
        limit = self.access.free_tease_limit()
        remaining = self.access.free_tease_remaining(user_id)
        display = build_ai_display(row, entitled=active)
        return MeAiOut(
            **display,
            free_tease_remaining=remaining,
            free_tease_limit=limit,
        )

    def verify_for_user(
        self,
        principal: Principal,
        *,
        signed_transaction: str | None = None,
        signed_renewal_info: str | None = None,
        transaction_id: str | None = None,
        original_transaction_id: str | None = None,
    ) -> MeAiOut:
        tx = self._resolve_transaction(
            signed_transaction=signed_transaction,
            transaction_id=transaction_id,
            original_transaction_id=original_transaction_id,
        )
        self._apply_transaction(principal.user_id, tx, signed_renewal_info=signed_renewal_info)
        log.info(
            "ai_verify_ok",
            user_id=principal.user_id,
            transaction_id=tx.transaction_id,
            original_transaction_id=tx.original_transaction_id,
            product_id=tx.product_id,
        )
        return self.get_me_ai(principal.user_id)

    def restore_for_user(
        self,
        principal: Principal,
        transactions: list[dict[str, Any]],
    ) -> MeAiOut:
        if not transactions:
            raise ValidationAppError("Provide at least one transaction to restore.")
        for item in transactions:
            signed = item.get("signedTransaction") or item.get("signed_transaction")
            tid = item.get("transactionId") or item.get("transaction_id")
            otid = item.get("originalTransactionId") or item.get("original_transaction_id")
            tx = self._resolve_transaction(
                signed_transaction=signed,
                transaction_id=tid,
                original_transaction_id=otid,
            )
            self._apply_transaction(principal.user_id, tx, allow_rebind_same_user=True)
        log.info("ai_restore_ok", user_id=principal.user_id, count=len(transactions))
        return self.get_me_ai(principal.user_id)

    def handle_apple_notification(self, body: dict[str, Any] | bytes | str) -> dict:
        """ASSN V2 — body is JSON with signedPayload, or raw signedPayload string."""
        if isinstance(body, (bytes, bytearray)):
            import json

            try:
                body = json.loads(body.decode("utf-8"))
            except Exception:
                body = {"signedPayload": body.decode("utf-8")}
        if isinstance(body, str):
            body = {"signedPayload": body}
        if not isinstance(body, dict):
            raise ValidationAppError("Invalid Apple notification body.")

        signed_payload = body.get("signedPayload") or body.get("signed_payload")
        if not signed_payload:
            raise ValidationAppError("Missing signedPayload.")

        outer = self.apple.decode_notification(str(signed_payload))
        notification_uuid = str(outer.get("notificationUUID") or outer.get("notificationUuid") or "")
        notification_type = str(outer.get("notificationType") or "")
        subtype = str(outer.get("subtype") or "") or None

        event_id = notification_uuid or f"apple_notif_{uuid4().hex}"
        inserted = self.repo.try_record_event(
            provider="apple",
            event_id=event_id,
            event_type=notification_type,
            payload=outer,
        )
        if not inserted:
            log.info("apple_assn_duplicate", event_id=event_id, type=notification_type)
            return {"received": True}

        if notification_type == "TEST":
            log.info("apple_assn_test", event_id=event_id)
            return {"received": True}

        data = outer.get("data") or {}
        signed_tx = data.get("signedTransactionInfo")
        if not signed_tx:
            log.info("apple_assn_no_transaction", type=notification_type)
            return {"received": True}

        payload = decode_jws_payload(str(signed_tx))
        tx = transaction_from_payload(payload)
        # Prefer App Store API re-fetch when configured
        if self.apple.configured() and tx.transaction_id:
            try:
                tx = self.apple.get_transaction(tx.transaction_id)
            except Exception:
                log.warning("apple_assn_refetch_failed", transaction_id=tx.transaction_id)

        row = self.db.scalars(
            select(models.AiEntitlement).where(
                models.AiEntitlement.original_transaction_id == tx.original_transaction_id
            )
        ).first()
        if row is None:
            log.info(
                "apple_assn_unknown_original",
                original_transaction_id=tx.original_transaction_id,
                type=notification_type,
            )
            return {"received": True}

        status = self._status_from_notification(notification_type, subtype, tx)
        self._write_entitlement_row(
            user_id=row.user_id,
            tx=tx,
            status=status,
            existing=row,
        )
        log.info(
            "apple_assn_applied",
            event_id=event_id,
            type=notification_type,
            subtype=subtype,
            user_id=row.user_id,
            status=status,
        )
        return {"received": True}

    def grant_manual(
        self,
        *,
        user_id: str,
        product_id: str = "ai.pro.monthly",
        days: int = 30,
    ) -> models.AiEntitlement:
        """QA complimentary AI access (source=manual)."""
        now = _utcnow()
        from datetime import timedelta

        product = self.repo.get_product(product_id)
        existing = self.access.get_entitlement_row(user_id)
        ends = now + timedelta(days=days)
        if existing:
            existing.status = "active"
            existing.starts_at = existing.starts_at or now
            existing.ends_at = ends
            existing.source = "manual"
            existing.plan = product_id
            existing.product_id = product.id if product else product_id
            existing.apple_product_id = product.apple_product_id if product else product_id
            existing.updated_at = now
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        row = models.AiEntitlement(
            id=str(uuid4()),
            user_id=user_id,
            product_id=product.id if product else None,
            plan=product_id,
            apple_product_id=product.apple_product_id if product else product_id,
            original_transaction_id=f"manual:{uuid4().hex}",
            latest_transaction_id=f"manual:{uuid4().hex}",
            status="active",
            starts_at=now,
            ends_at=ends,
            environment="Sandbox",
            source="manual",
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    # --- internals ---------------------------------------------------------

    def _resolve_transaction(
        self,
        *,
        signed_transaction: str | None,
        transaction_id: str | None,
        original_transaction_id: str | None,
    ) -> VerifiedAppleTransaction:
        if signed_transaction:
            return self.apple.verify_signed_transaction(signed_transaction)
        tid = (transaction_id or original_transaction_id or "").strip()
        if not tid:
            raise ValidationAppError(
                "Provide signedTransaction or transactionId.",
                fields={"transactionId": "required"},
            )
        return self.apple.get_transaction(tid)

    def _apply_transaction(
        self,
        user_id: str,
        tx: VerifiedAppleTransaction,
        *,
        signed_renewal_info: str | None = None,
        allow_rebind_same_user: bool = True,
    ) -> models.AiEntitlement:
        if not tx.original_transaction_id or not tx.transaction_id:
            raise ValidationAppError("Apple transaction missing ids.")

        # Idempotent on transactionId
        if not self.repo.try_record_event(
            provider="apple_tx",
            event_id=str(tx.transaction_id),
            event_type="verify",
            payload=tx.raw or {},
        ):
            existing = self.access.get_entitlement_row(user_id)
            if existing and existing.original_transaction_id == tx.original_transaction_id:
                return existing
            # Same tx already processed — still ensure ownership rules
            owned = self.db.scalars(
                select(models.AiEntitlement).where(
                    models.AiEntitlement.original_transaction_id == tx.original_transaction_id
                )
            ).first()
            if owned and owned.user_id != user_id:
                raise ConflictError(
                    "This Apple subscription is already linked to another account.",
                    fields={"originalTransactionId": "conflict"},
                )
            if owned:
                return owned

        expected_bundle = (self.settings.apple_bundle_id or "").strip()
        if expected_bundle and tx.bundle_id and tx.bundle_id != expected_bundle:
            raise ValidationAppError(
                "Transaction bundle does not match this app.",
                fields={"bundleId": "mismatch"},
            )

        product = self.db.scalars(
            select(models.BillingProduct).where(
                models.BillingProduct.type == "ai",
                models.BillingProduct.active.is_(True),
                models.BillingProduct.apple_product_id == tx.product_id,
            )
        ).first()
        if product is None:
            raise ValidationAppError(
                "Unknown AI product.",
                fields={"productId": "unknown"},
            )

        env_cfg = (self.settings.apple_environment or "Sandbox").strip().lower()
        if env_cfg == "production" and tx.environment == "Sandbox":
            # Allow sandbox in production only via explicit fallback in API client; reject strict prod
            if (self.settings.app_env or "").lower() == "production":
                raise ValidationAppError(
                    "Sandbox transactions are not accepted in production.",
                    fields={"environment": "sandbox"},
                )

        owned = self.db.scalars(
            select(models.AiEntitlement).where(
                models.AiEntitlement.original_transaction_id == tx.original_transaction_id
            )
        ).first()
        if owned is not None and owned.user_id != user_id:
            raise ConflictError(
                "This Apple subscription is already linked to another account.",
                fields={"originalTransactionId": "conflict"},
            )

        status = "active"
        if tx.revocation_date is not None:
            status = "revoked"
        elif tx.expires_date is not None and tx.expires_date <= _utcnow():
            status = "expired"

        existing_user_row = self.access.get_entitlement_row(user_id)
        return self._write_entitlement_row(
            user_id=user_id,
            tx=tx,
            status=status,
            existing=owned or existing_user_row,
            product=product,
        )

    def _write_entitlement_row(
        self,
        *,
        user_id: str,
        tx: VerifiedAppleTransaction,
        status: str,
        existing: models.AiEntitlement | None,
        product: models.BillingProduct | None = None,
    ) -> models.AiEntitlement:
        now = _utcnow()
        if product is None:
            product = self.db.scalars(
                select(models.BillingProduct).where(
                    models.BillingProduct.apple_product_id == tx.product_id
                )
            ).first()

        if existing is None:
            existing = models.AiEntitlement(
                id=str(uuid4()),
                user_id=user_id,
                created_at=now,
            )
            self.db.add(existing)

        # If user row exists with different original id and we're binding a new one that is free — OK
        if existing.user_id != user_id:
            raise ConflictError("Entitlement ownership conflict.")

        existing.product_id = product.id if product else existing.product_id
        existing.plan = product.id if product else tx.product_id
        existing.apple_product_id = tx.product_id
        existing.original_transaction_id = tx.original_transaction_id
        existing.latest_transaction_id = tx.transaction_id
        existing.status = status
        existing.starts_at = tx.purchase_date or existing.starts_at or now
        existing.ends_at = tx.expires_date
        existing.environment = tx.environment
        existing.source = "apple"
        existing.raw_last_payload = tx.raw
        existing.updated_at = now
        self.db.add(existing)
        self.db.commit()
        self.db.refresh(existing)
        return existing

    def _status_from_notification(
        self,
        notification_type: str,
        subtype: str | None,
        tx: VerifiedAppleTransaction,
    ) -> str:
        nt = notification_type.upper()
        if nt in {"REFUND", "REVOKE"}:
            return "revoked" if nt == "REVOKE" else "refunded"
        if nt in {"EXPIRED", "GRACE_PERIOD_EXPIRED"}:
            return "expired"
        if nt == "DID_FAIL_TO_RENEW":
            if (subtype or "").upper() == "GRACE_PERIOD":
                return "grace"
            return "billing_retry"
        if nt in {"DID_RENEW", "SUBSCRIBED", "OFFER_REDEEMED", "ONE_TIME_CHARGE"}:
            if tx.revocation_date:
                return "revoked"
            if tx.expires_date and tx.expires_date <= _utcnow():
                return "expired"
            return "active"
        if nt == "DID_CHANGE_RENEWAL_STATUS":
            # Keep access until period end
            if tx.expires_date and tx.expires_date > _utcnow():
                return "active"
            return "expired"
        # Default: derive from dates
        if tx.revocation_date:
            return "revoked"
        if tx.expires_date and tx.expires_date > _utcnow():
            return "active"
        return "expired"
