#!/usr/bin/env python3
"""Grant a complimentary boost for staging QA (source=manual).

    .venv/bin/python -m scripts.grant_boost --email trainer@tactech.app --days 7
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db import models
from app.db.session import SessionLocal
from app.services.billing_service import BillingService


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant manual coach boost")
    parser.add_argument("--email", default="trainer@tactech.app")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--product-id", default="boost.featured.7d")
    parser.add_argument("--days", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("tactech.grant_boost")
    db = SessionLocal()
    try:
        if args.user_id:
            user = db.get(models.User, args.user_id)
        else:
            user = db.scalars(select(models.User).where(models.User.email == args.email)).first()
        if user is None or user.role != "trainer":
            raise SystemExit("Trainer user not found.")
        trainer = db.scalars(
            select(models.TrainerProfile).where(models.TrainerProfile.user_id == user.id)
        ).first()
        if trainer is None:
            raise SystemExit("Trainer profile not found.")

        boost = BillingService(db, settings).grant_manual_boost(
            user_id=user.id,
            trainer_id=trainer.id,
            product_id=args.product_id,
            duration_days=args.days,
        )
        log.info(
            "grant_boost_ok",
            boost_id=boost.id,
            user_id=user.id,
            ends_at=boost.ends_at.isoformat() if boost.ends_at else None,
        )
        print(f"OK boost={boost.id} endsAt={boost.ends_at}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
