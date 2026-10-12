from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories.entitlements import EntitlementsRepository
from app.schemas.discovery import AiEntitlementOut, BoostEntitlementOut, EntitlementsOut

log = get_logger("tactech.entitlements")


class EntitlementService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = EntitlementsRepository(db)

    def get_entitlements(self, user_id: str) -> EntitlementsOut:
        """Always 200 with ai + boost. Boost slice is live from coach_boosts windows."""
        from app.repositories.billing import BillingRepository
        from app.services.ai_access import AiAccessService
        from app.services.ai_pro_display import build_ai_display
        from app.core.config import get_settings

        BillingRepository(self.db).expire_stale()
        access = AiAccessService(self.db, get_settings())
        ai_row = access.get_entitlement_row(user_id)
        entitled = access.is_entitlement_active(user_id)
        display = build_ai_display(ai_row, entitled=entitled)
        ai = AiEntitlementOut(**display)

        boost_row = self.repo.active_boost_for_user(user_id)
        boost = BoostEntitlementOut(
            active=boost_row is not None,
            tier=boost_row.tier if boost_row else None,
            starts_at=boost_row.starts_at if boost_row else None,
            ends_at=boost_row.ends_at if boost_row else None,
            source=(boost_row.source or "stripe") if boost_row else None,
        )
        return EntitlementsOut(ai=ai, boost=boost)

    def is_boost_active(self, user_id: str) -> bool:
        return self.repo.active_boost_for_user(user_id) is not None

    def active_boost_user_ids(self, user_ids: list[str]) -> set[str]:
        return self.repo.active_boost_user_ids(user_ids)
