"""Phase 2 trainer Boost — checkout, webhook idempotency, extend, expiry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import ValidationAppError
from app.db import models
from app.db.session import SessionLocal
from app.main import app
from app.services.billing.provider import CheckoutSessionResult
from app.services.billing_service import BillingService


class FakeStripe:
    name = "stripe"

    def __init__(self) -> None:
        self.sessions: dict[str, CheckoutSessionResult] = {}
        self.fail_signature = False
        self.events: list[dict[str, Any]] = []

    def create_checkout_session(
        self,
        *,
        price_id: str,
        success_url: str,
        cancel_url: str,
        client_reference_id: str,
        metadata: dict[str, str],
    ) -> CheckoutSessionResult:
        sid = f"cs_test_{uuid4().hex[:16]}"
        result = CheckoutSessionResult(
            session_id=sid,
            url=f"https://checkout.stripe.com/c/pay/{sid}",
            payment_intent_id=f"pi_test_{uuid4().hex[:10]}",
            amount_total=999,
            currency="usd",
            payment_status="unpaid",
            status="open",
            metadata=dict(metadata),
            raw={
                "id": sid,
                "client_reference_id": client_reference_id,
                "metadata": dict(metadata),
                "payment_status": "unpaid",
                "status": "open",
                "amount_total": 999,
                "currency": "usd",
                "payment_intent": f"pi_test_{uuid4().hex[:10]}",
            },
        )
        # keep PI consistent on raw
        result.raw["payment_intent"] = result.payment_intent_id
        self.sessions[sid] = result
        return result

    def retrieve_checkout_session(self, session_id: str) -> CheckoutSessionResult:
        session = self.sessions.get(session_id)
        if session is None:
            raise ValidationAppError("Checkout session not found.")
        return session

    def mark_paid(self, session_id: str) -> CheckoutSessionResult:
        s = self.sessions[session_id]
        s.payment_status = "paid"
        s.status = "complete"
        if isinstance(s.raw, dict):
            s.raw["payment_status"] = "paid"
            s.raw["status"] = "complete"
        return s

    def construct_webhook_event(self, payload: bytes, signature_header: str | None) -> Any:
        if self.fail_signature or not signature_header:
            raise ValidationAppError(
                "Invalid Stripe webhook signature.",
                fields={"stripe": "bad_signature"},
            )
        import json

        return json.loads(payload.decode("utf-8"))


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> dict:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "token": body["accessToken"],
        "user_id": body["user"]["id"],
        "role": body["user"]["role"],
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def users(client: TestClient) -> dict:
    settings = get_settings()
    return {
        "trainer": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
        "trainee": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
        "settings": settings,
    }


@pytest.fixture()
def fake_stripe() -> FakeStripe:
    return FakeStripe()


def _override_billing(fake: FakeStripe):
    from app.api.deps import get_billing_service

    settings = get_settings()

    def override():
        db = SessionLocal()
        try:
            yield BillingService(db, settings, provider=fake)
        finally:
            db.close()

    app.dependency_overrides[get_billing_service] = override
    return get_billing_service


def _ensure_price() -> None:
    db = SessionLocal()
    try:
        for pid in ("boost.featured.7d", "boost.featured.30d"):
            row = db.get(models.BillingProduct, pid)
            if row is None:
                continue
            if not row.stripe_price_id:
                row.stripe_price_id = f"price_test_{pid}"
            row.active = True
        db.commit()
    finally:
        db.close()


def test_products_list(client: TestClient, users: dict) -> None:
    _ensure_price()
    res = client.get("/billing/products?type=boost", headers=_auth(users["trainer"]["token"]))
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    ids = {i["id"] for i in items}
    assert "boost.featured.7d" in ids
    assert "boost.featured.30d" in ids
    by_id = {i["id"]: i for i in items}
    assert by_id["boost.featured.7d"]["currency"] == "usd"
    assert "stripe" in by_id["boost.featured.7d"].get("providers", ["stripe"])
    for i in items:
        assert "stripePriceId" not in i
        assert i["amountMinor"] > 0
        assert i["currency"] in {"usd", "pkr"}


def test_checkout_rejects_non_trainer(client: TestClient, users: dict, fake_stripe: FakeStripe) -> None:
    _ensure_price()
    res = client.post(
        "/billing/boost/checkout",
        headers=_auth(users["trainee"]["token"]),
        json={"productId": "boost.featured.7d"},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


def test_checkout_and_confirm_activates(
    client: TestClient, users: dict, fake_stripe: FakeStripe
) -> None:
    _ensure_price()
    dep = _override_billing(fake_stripe)
    try:
        create = client.post(
            "/billing/boost/checkout",
            headers=_auth(users["trainer"]["token"]),
            json={"productId": "boost.featured.7d"},
        )
        assert create.status_code == 200, create.text
        body = create.json()
        assert body["checkoutSessionId"].startswith("cs_test_")
        assert body["url"].startswith("https://checkout.stripe.com/")
        sid = body["checkoutSessionId"]

        fake_stripe.mark_paid(sid)
        confirm = client.post(
            "/billing/boost/confirm",
            headers=_auth(users["trainer"]["token"]),
            json={"checkoutSessionId": sid},
        )
        assert confirm.status_code == 200, confirm.text
        me = confirm.json()
        assert me["active"] is True
        assert me["tier"] == "featured"
        assert me["source"] == "stripe"
        assert me["endsAt"]

        ent = client.get("/me/entitlements", headers=_auth(users["trainer"]["token"]))
        assert ent.status_code == 200
        assert ent.json()["boost"]["active"] is True
        assert ent.json()["boost"]["source"] == "stripe"

        coaches = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
        assert coaches.status_code == 200
        mine = [c for c in coaches.json()["items"] if c["userId"] == users["trainer"]["user_id"]]
        assert mine, "trainer should be public in seed"
        assert mine[0]["boostActive"] is True
        assert coaches.json()["items"][0]["boostActive"] is True
    finally:
        app.dependency_overrides.pop(dep, None)


def test_webhook_idempotent_no_double_extend(
    client: TestClient, users: dict, fake_stripe: FakeStripe
) -> None:
    import json

    _ensure_price()
    dep = _override_billing(fake_stripe)
    try:
        create = client.post(
            "/billing/boost/checkout",
            headers=_auth(users["trainer"]["token"]),
            json={"productId": "boost.featured.7d"},
        )
        sid = create.json()["checkoutSessionId"]
        paid = fake_stripe.mark_paid(sid)

        event = {
            "id": f"evt_{uuid4().hex}",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": sid,
                    "metadata": paid.metadata,
                    "client_reference_id": users["trainer"]["user_id"],
                    "payment_status": "paid",
                    "status": "complete",
                    "amount_total": 999,
                    "currency": "usd",
                    "payment_intent": paid.payment_intent_id,
                }
            },
        }
        payload = json.dumps(event).encode()
        r1 = client.post(
            "/billing/webhooks/stripe",
            content=payload,
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )
        assert r1.status_code == 200, r1.text

        me1 = client.get("/me/boost", headers=_auth(users["trainer"]["token"]))
        assert me1.json()["active"] is True
        ends_before = me1.json()["endsAt"]

        r2 = client.post(
            "/billing/webhooks/stripe",
            content=payload,
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )
        assert r2.status_code == 200
        me2 = client.get("/me/boost", headers=_auth(users["trainer"]["token"]))
        assert me2.json()["endsAt"] == ends_before

        fake_stripe.fail_signature = True
        bad = client.post(
            "/billing/webhooks/stripe",
            content=payload,
            headers={"Stripe-Signature": "bad"},
        )
        assert bad.status_code == 400
        fake_stripe.fail_signature = False
    finally:
        app.dependency_overrides.pop(dep, None)


def test_second_purchase_extends_ends_at(
    client: TestClient, users: dict, fake_stripe: FakeStripe
) -> None:
    import json

    _ensure_price()
    settings = get_settings()
    dep = _override_billing(fake_stripe)
    try:
        db = SessionLocal()
        try:
            svc = BillingService(db, settings, provider=fake_stripe)
            trainer = db.scalars(
                select(models.TrainerProfile).where(
                    models.TrainerProfile.user_id == users["trainer"]["user_id"]
                )
            ).first()
            assert trainer
            for b in db.scalars(
                select(models.CoachBoost).where(
                    models.CoachBoost.user_id == users["trainer"]["user_id"]
                )
            ).all():
                b.status = "expired"
                b.ends_at = datetime.now(timezone.utc) - timedelta(days=1)
            db.commit()
            first = svc.grant_manual_boost(
                user_id=users["trainer"]["user_id"],
                trainer_id=trainer.id,
                product_id="boost.featured.7d",
                duration_days=7,
            )
            ends1 = first.ends_at
        finally:
            db.close()

        create = client.post(
            "/billing/boost/checkout",
            headers=_auth(users["trainer"]["token"]),
            json={"productId": "boost.featured.7d"},
        )
        assert create.status_code == 200, create.text
        sid = create.json()["checkoutSessionId"]
        paid = fake_stripe.mark_paid(sid)

        event = {
            "id": f"evt_{uuid4().hex}",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": sid,
                    "metadata": paid.metadata,
                    "client_reference_id": users["trainer"]["user_id"],
                    "payment_status": "paid",
                    "status": "complete",
                    "amount_total": 999,
                    "currency": "usd",
                    "payment_intent": paid.payment_intent_id,
                }
            },
        }
        r = client.post(
            "/billing/webhooks/stripe",
            content=json.dumps(event).encode(),
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )
        assert r.status_code == 200, r.text

        me = client.get("/me/boost", headers=_auth(users["trainer"]["token"]))
        assert me.status_code == 200
        ends2 = datetime.fromisoformat(me.json()["endsAt"].replace("Z", "+00:00"))
        assert ends1 is not None
        delta = ends2 - ends1
        assert timedelta(days=6, hours=23) <= delta <= timedelta(days=7, hours=1)
    finally:
        app.dependency_overrides.pop(dep, None)


def test_expiry_flips_boost_active_false(client: TestClient, users: dict) -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for b in db.scalars(
            select(models.CoachBoost).where(
                models.CoachBoost.user_id == users["trainer"]["user_id"],
                models.CoachBoost.status == "active",
            )
        ).all():
            b.ends_at = now - timedelta(minutes=1)
            b.status = "active"
        db.commit()
    finally:
        db.close()

    ent = client.get("/me/entitlements", headers=_auth(users["trainer"]["token"]))
    assert ent.status_code == 200
    assert ent.json()["boost"]["active"] is False

    coaches = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
    mine = [c for c in coaches.json()["items"] if c["userId"] == users["trainer"]["user_id"]]
    if mine:
        assert mine[0]["boostActive"] is False


def test_contact_still_works_without_boost(client: TestClient, users: dict) -> None:
    coaches = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
    assert coaches.status_code == 200
    items = coaches.json()["items"]
    assert items
    # Prefer a coach that is not the assigned-only private case — any public
    coach_id = items[0]["id"]
    res = client.post(
        f"/coaches/{coach_id}/contact",
        headers=_auth(users["trainee"]["token"]),
        json={},
    )
    assert res.status_code == 200, res.text
    assert res.json()["threadId"]
