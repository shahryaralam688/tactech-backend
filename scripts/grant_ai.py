#!/usr/bin/env python3
"""Grant complimentary AI entitlement for staging QA (source=manual).

    .venv/bin/python -m scripts.grant_ai --email trainee@tactech.app --days 30
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db import models
from app.db.session import SessionLocal
from app.services.ai_billing_service import AiBillingService


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant manual AI entitlement")
    parser.add_argument("--email", default="trainee@tactech.app")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--product-id", default="ai.pro.monthly")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("tactech.grant_ai")
    db = SessionLocal()
    try:
        if args.user_id:
            user = db.get(models.User, args.user_id)
        else:
            user = db.scalars(select(models.User).where(models.User.email == args.email)).first()
        if user is None:
            raise SystemExit("User not found.")
        row = AiBillingService(db, settings).grant_manual(
            user_id=user.id,
            product_id=args.product_id,
            days=args.days,
        )
        log.info("grant_ai_ok", user_id=user.id, ends_at=row.ends_at)
        print(f"OK ai entitlement user={user.id} endsAt={row.ends_at} status={row.status}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
