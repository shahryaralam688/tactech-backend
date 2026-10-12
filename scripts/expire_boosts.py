#!/usr/bin/env python3
"""Mark expired coach boosts. Run every 5–15 minutes via cron.

    .venv/bin/python -m scripts.expire_boosts
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.services.billing_service import BillingService


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("tactech.expire_boosts")
    db = SessionLocal()
    try:
        n = BillingService(db, settings).expire_stale()
        log.info("expire_boosts_done", count=n)
    finally:
        db.close()


if __name__ == "__main__":
    main()
