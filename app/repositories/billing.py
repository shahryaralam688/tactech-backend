from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BillingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- products ----------------------------------------------------------

    def list_products(
        self,
        *,
        type: str | None = None,
        active_only: bool = True,
        currency: str | None = None,
    ) -> list[models.BillingProduct]:
        stmt = select(models.BillingProduct).order_by(
            models.BillingProduct.sort_order.asc(),
            models.BillingProduct.id.asc(),
        )
        if type:
            stmt = stmt.where(models.BillingProduct.type == type)
        if active_only:
            stmt = stmt.where(models.BillingProduct.active.is_(True))
        if currency:
            stmt = stmt.where(models.BillingProduct.currency == currency.lower())
        return list(self.db.scalars(stmt).all())

    def get_product(self, product_id: str) -> models.BillingProduct | None:
        return self.db.get(models.BillingProduct, product_id)

    def upsert_product(self, row: models.BillingProduct) -> models.BillingProduct:
        self.db.merge(row)
        self.db.commit()
        return self.db.get(models.BillingProduct, row.id)  # type: ignore[return-value]

    # --- boosts ------------------------------------------------------------

    def get_boost(self, boost_id: str) -> models.CoachBoost | None:
        return self.db.get(models.CoachBoost, boost_id)

    def get_boost_by_checkout_session(self, session_id: str) -> models.CoachBoost | None:
        return self.db.scalars(
            select(models.CoachBoost).where(
                models.CoachBoost.stripe_checkout_session_id == session_id
            )
        ).first()

    def active_boost_for_user(
        self, user_id: str, *, now: datetime | None = None
    ) -> models.CoachBoost | None:
        now = now or _utcnow()
        return self.db.scalars(
            select(models.CoachBoost)
            .where(
                models.CoachBoost.user_id == user_id,
                models.CoachBoost.status == "active",
                models.CoachBoost.starts_at.is_not(None),
                models.CoachBoost.ends_at.is_not(None),
                models.CoachBoost.starts_at <= now,
                models.CoachBoost.ends_at > now,
            )
            .order_by(models.CoachBoost.ends_at.desc())
        ).first()

    def list_boosts_for_user(self, user_id: str, *, limit: int = 10) -> list[models.CoachBoost]:
        return list(
            self.db.scalars(
                select(models.CoachBoost)
                .where(models.CoachBoost.user_id == user_id)
                .order_by(models.CoachBoost.created_at.desc())
                .limit(limit)
            ).all()
        )

    def create_pending_boost(
        self,
        *,
        user_id: str,
        trainer_id: str,
        product: models.BillingProduct,
        checkout_session_id: str | None = None,
        provider: str = "stripe",
        merchant_txn_id: str | None = None,
    ) -> models.CoachBoost:
        now = _utcnow()
        row = models.CoachBoost(
            id=str(uuid4()),
            user_id=user_id,
            trainer_id=trainer_id,
            product_id=product.id,
            tier=product.tier,
            status="pending",
            starts_at=None,
            ends_at=None,
            stripe_checkout_session_id=checkout_session_id,
            stripe_payment_intent_id=None,
            amount_minor=product.amount_minor,
            currency=product.currency,
            source=provider,
            provider=provider,
            merchant_txn_id=merchant_txn_id,
            payment_ref=checkout_session_id or merchant_txn_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_boost_by_provider_payment(
        self, provider: str, provider_payment_id: str
    ) -> models.CoachBoost | None:
        return self.db.scalars(
            select(models.CoachBoost).where(
                models.CoachBoost.provider == provider,
                models.CoachBoost.provider_payment_id == provider_payment_id,
            )
        ).first()

    def get_boost_by_merchant_txn(self, merchant_txn_id: str) -> models.CoachBoost | None:
        return self.db.scalars(
            select(models.CoachBoost).where(models.CoachBoost.merchant_txn_id == merchant_txn_id)
        ).first()

    def create_attempt(
        self,
        *,
        user_id: str,
        trainer_id: str,
        product: models.BillingProduct,
        provider: str,
        merchant_txn_id: str,
        redirect_url: str | None = None,
        stripe_checkout_session_id: str | None = None,
        provider_payload: dict | None = None,
    ) -> models.BoostCheckoutAttempt:
        now = _utcnow()
        row = models.BoostCheckoutAttempt(
            id=str(uuid4()),
            user_id=user_id,
            trainer_id=trainer_id,
            product_id=product.id,
            provider=provider,
            status="created",
            amount_minor=product.amount_minor,
            currency=product.currency,
            merchant_txn_id=merchant_txn_id,
            provider_payment_id=None,
            redirect_url=redirect_url,
            stripe_checkout_session_id=stripe_checkout_session_id,
            provider_payload=provider_payload,
            created_at=now,
            updated_at=now,
            paid_at=None,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_attempt(self, attempt_id: str) -> models.BoostCheckoutAttempt | None:
        return self.db.get(models.BoostCheckoutAttempt, attempt_id)

    def get_attempt_by_merchant_txn(self, merchant_txn_id: str) -> models.BoostCheckoutAttempt | None:
        return self.db.scalars(
            select(models.BoostCheckoutAttempt).where(
                models.BoostCheckoutAttempt.merchant_txn_id == merchant_txn_id
            )
        ).first()

    def save_attempt(self, row: models.BoostCheckoutAttempt) -> models.BoostCheckoutAttempt:
        row.updated_at = _utcnow()
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def save_boost(self, row: models.CoachBoost) -> models.CoachBoost:
        row.updated_at = _utcnow()
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def expire_stale(self, *, now: datetime | None = None) -> int:
        now = now or _utcnow()
        result = self.db.execute(
            update(models.CoachBoost)
            .where(
                models.CoachBoost.status == "active",
                models.CoachBoost.ends_at.is_not(None),
                models.CoachBoost.ends_at <= now,
            )
            .values(status="expired", updated_at=now)
        )
        self.db.commit()
        return int(result.rowcount or 0)

    # --- payment events ----------------------------------------------------

    def try_record_event(
        self,
        *,
        provider: str,
        event_id: str,
        event_type: str | None,
        payload: dict,
    ) -> bool:
        """Insert idempotency row. Returns False if eventId already seen."""
        now = _utcnow()
        row = models.PaymentEvent(
            id=str(uuid4()),
            provider=provider,
            event_id=event_id,
            type=event_type,
            payload=payload,
            processed_at=now,
        )
        self.db.add(row)
        try:
            self.db.commit()
            return True
        except IntegrityError:
            self.db.rollback()
            return False


def extend_or_start_window(
    *,
    existing: models.CoachBoost | None,
    duration_days: int,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Stacking: extend from current endsAt if active; else start from now."""
    now = now or _utcnow()
    delta = timedelta(days=duration_days)
    if existing is not None and existing.ends_at is not None and existing.ends_at > now:
        starts = existing.starts_at or now
        ends = existing.ends_at + delta
        return starts, ends
    return now, now + delta
