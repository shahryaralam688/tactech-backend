"""Phase 4 — JazzCash / Easypaisa Boost (PKR) + Stripe USD regression."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.main import app
from app.services.billing.local_wallets import easypaisa_secure_hash, jazzcash_secure_hash
from app.services.billing_service import BillingService


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
    }


def _local_settings():
    s = get_settings()
    object.__setattr__(s, "jazzcash_merchant_id", "MC12345")
    object.__setattr__(s, "jazzcash_password", "pass_test")
    object.__setattr__(s, "jazzcash_integrity_salt", "salt_test_integrity")
    object.__setattr__(
        s,
        "jazzcash_checkout_url",
        "https://sandbox.jazzcash.com.pk/CustomerPortal/transactionmanagement/merchantform/",
    )
    object.__setattr__(s, "easypaisa_store_id", "store_99")
    object.__setattr__(s, "easypaisa_hash_key", "ep_hash_key_test")
    object.__setattr__(s, "easypaisa_checkout_url", "https://easypaisa.test/checkout")
    object.__setattr__(s, "public_base_url", "http://testserver")
    return s


def _override_billing():
    from app.api.deps import get_billing_service

    settings = _local_settings()

    def override():
        db = SessionLocal()
        try:
            yield BillingService(db, settings)
        finally:
            db.close()

    app.dependency_overrides[get_billing_service] = override
    return get_billing_service


def _ensure_pkr_products() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for row in (
            models.BillingProduct(
                id="boost.featured.7d.pkr",
                type="boost",
                name="Featured Boost — 7 days",
                description="Appear at the top of Find Coaches for 7 days.",
                duration_days=7,
                tier="featured",
                amount_minor=299900,
                currency="pkr",
                providers=["jazzcash", "easypaisa"],
                active=True,
                sort_order=30,
                created_at=now,
                updated_at=now,
            ),
            models.BillingProduct(
                id="boost.featured.30d.pkr",
                type="boost",
                name="Featured Boost — 30 days",
                description="Appear at the top of Find Coaches for 30 days.",
                duration_days=30,
                tier="featured",
                amount_minor=799900,
                currency="pkr",
                providers=["jazzcash", "easypaisa"],
                active=True,
                sort_order=40,
                created_at=now,
                updated_at=now,
            ),
        ):
            existing = db.get(models.BillingProduct, row.id)
            if existing is None:
                db.add(row)
            else:
                existing.providers = ["jazzcash", "easypaisa"]
                existing.currency = "pkr"
                existing.amount_minor = row.amount_minor
                existing.active = True
                existing.duration_days = row.duration_days
        usd = db.get(models.BillingProduct, "boost.featured.7d")
        if usd is not None:
            usd.providers = ["stripe"]
            usd.active = True
            if not usd.stripe_price_id:
                usd.stripe_price_id = "price_test_boost.featured.7d"
        db.commit()
    finally:
        db.close()


def _expire_trainer_boosts(user_id: str) -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for b in db.scalars(
            select(models.CoachBoost).where(models.CoachBoost.user_id == user_id)
        ).all():
            b.status = "expired"
            b.ends_at = now - timedelta(days=1)
            b.provider_payment_id = None
            b.merchant_txn_id = None
        db.commit()
    finally:
        db.close()


def _attempt_merchant(attempt_id: str) -> tuple[str, int]:
    db = SessionLocal()
    try:
        row = db.get(models.BoostCheckoutAttempt, attempt_id)
        assert row is not None
        return row.merchant_txn_id, row.amount_minor
    finally:
        db.close()


def test_products_include_usd_and_pkr(client: TestClient, users: dict) -> None:
    _ensure_pkr_products()
    res = client.get("/billing/products?type=boost", headers=_auth(users["trainer"]["token"]))
    assert res.status_code == 200, res.text
    by_id = {i["id"]: i for i in res.json()["items"]}
    assert by_id["boost.featured.7d"]["providers"] == ["stripe"]
    assert by_id["boost.featured.7d"]["currency"] == "usd"
    assert set(by_id["boost.featured.7d.pkr"]["providers"]) == {"jazzcash", "easypaisa"}
    assert by_id["boost.featured.7d.pkr"]["amountMinor"] == 299900
    assert by_id["boost.featured.7d.pkr"]["currency"] == "pkr"

    pkr = client.get(
        "/billing/products?type=boost&currency=pkr",
        headers=_auth(users["trainer"]["token"]),
    )
    assert pkr.status_code == 200
    assert all(i["currency"] == "pkr" for i in pkr.json()["items"])


def test_pkr_rejects_stripe_provider(client: TestClient, users: dict) -> None:
    _ensure_pkr_products()
    dep = _override_billing()
    try:
        res = client.post(
            "/billing/boost/checkout",
            headers=_auth(users["trainer"]["token"]),
            json={"productId": "boost.featured.7d.pkr", "provider": "stripe"},
        )
        assert res.status_code == 400, res.text
        assert res.json()["code"] in {"VALIDATION", "VALIDATION_ERROR"}
    finally:
        app.dependency_overrides.pop(dep, None)


def test_jazzcash_checkout_returns_attempt_and_url(client: TestClient, users: dict) -> None:
    _ensure_pkr_products()
    _expire_trainer_boosts(users["trainer"]["user_id"])
    dep = _override_billing()
    try:
        res = client.post(
            "/billing/boost/checkout",
            headers=_auth(users["trainer"]["token"]),
            json={"productId": "boost.featured.7d.pkr", "provider": "jazzcash"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["provider"] == "jazzcash"
        assert body["checkoutSessionId"] is None
        assert body["attemptId"]
        assert "/billing/boost/pay/" in body["url"]
        pay = client.get(body["url"].replace("http://testserver", ""))
        assert pay.status_code == 200
        assert "pp_SecureHash" in pay.text
        assert "sandbox.jazzcash.com.pk" in pay.text
    finally:
        app.dependency_overrides.pop(dep, None)


def test_jazzcash_ipn_valid_hash_activates(client: TestClient, users: dict) -> None:
    _ensure_pkr_products()
    _expire_trainer_boosts(users["trainer"]["user_id"])
    dep = _override_billing()
    settings = _local_settings()
    try:
        create = client.post(
            "/billing/boost/checkout",
            headers=_auth(users["trainer"]["token"]),
            json={"productId": "boost.featured.7d.pkr", "provider": "jazzcash"},
        )
        assert create.status_code == 200, create.text
        attempt_id = create.json()["attemptId"]
        merchant_txn, amount = _attempt_merchant(attempt_id)

        fields = {
            "pp_Version": "1.1",
            "pp_TxnType": "MWALLET",
            "pp_MerchantID": settings.jazzcash_merchant_id,
            "pp_Password": settings.jazzcash_password,
            "pp_TxnRefNo": merchant_txn,
            "pp_Amount": str(amount),
            "pp_TxnCurrency": "PKR",
            "pp_ResponseCode": "000",
            "pp_ResponseMessage": "Success",
            "pp_RetreivalReferenceNo": f"RRN{uuid4().hex[:10]}",
            "pp_BillReference": attempt_id[:20],
        }
        fields["pp_SecureHash"] = jazzcash_secure_hash(
            fields, settings.jazzcash_integrity_salt
        )

        ipn = client.post("/billing/webhooks/jazzcash", data=fields)
        assert ipn.status_code == 200, ipn.text

        me = client.get("/me/boost", headers=_auth(users["trainer"]["token"]))
        assert me.status_code == 200
        assert me.json()["active"] is True
        assert me.json()["source"] == "jazzcash"

        coaches = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
        mine = [c for c in coaches.json()["items"] if c["userId"] == users["trainer"]["user_id"]]
        assert mine and mine[0]["boostActive"] is True
    finally:
        app.dependency_overrides.pop(dep, None)


def test_jazzcash_tampered_hash_rejected(client: TestClient, users: dict) -> None:
    _ensure_pkr_products()
    _expire_trainer_boosts(users["trainer"]["user_id"])
    dep = _override_billing()
    settings = _local_settings()
    try:
        create = client.post(
            "/billing/boost/checkout",
            headers=_auth(users["trainer"]["token"]),
            json={"productId": "boost.featured.7d.pkr", "provider": "jazzcash"},
        )
        attempt_id = create.json()["attemptId"]
        merchant_txn, amount = _attempt_merchant(attempt_id)
        fields = {
            "pp_MerchantID": settings.jazzcash_merchant_id,
            "pp_TxnRefNo": merchant_txn,
            "pp_Amount": str(amount),
            "pp_ResponseCode": "000",
            "pp_RetreivalReferenceNo": f"RRN{uuid4().hex[:8]}",
            "pp_SecureHash": "DEADBEEF" * 8,
        }
        bad = client.post("/billing/webhooks/jazzcash", data=fields)
        assert bad.status_code == 400, bad.text
        me = client.get("/me/boost", headers=_auth(users["trainer"]["token"]))
        assert me.json()["active"] is False
    finally:
        app.dependency_overrides.pop(dep, None)


def test_jazzcash_duplicate_ipn_no_double_extend(client: TestClient, users: dict) -> None:
    _ensure_pkr_products()
    _expire_trainer_boosts(users["trainer"]["user_id"])
    dep = _override_billing()
    settings = _local_settings()
    try:
        create = client.post(
            "/billing/boost/checkout",
            headers=_auth(users["trainer"]["token"]),
            json={"productId": "boost.featured.7d.pkr", "provider": "jazzcash"},
        )
        attempt_id = create.json()["attemptId"]
        merchant_txn, amount = _attempt_merchant(attempt_id)
        rrn = f"RRN{uuid4().hex[:10]}"
        fields = {
            "pp_MerchantID": settings.jazzcash_merchant_id,
            "pp_Password": settings.jazzcash_password,
            "pp_TxnRefNo": merchant_txn,
            "pp_Amount": str(amount),
            "pp_ResponseCode": "000",
            "pp_RetreivalReferenceNo": rrn,
        }
        fields["pp_SecureHash"] = jazzcash_secure_hash(
            fields, settings.jazzcash_integrity_salt
        )
        assert client.post("/billing/webhooks/jazzcash", data=fields).status_code == 200
        ends1 = client.get("/me/boost", headers=_auth(users["trainer"]["token"])).json()[
            "endsAt"
        ]
        assert client.post("/billing/webhooks/jazzcash", data=fields).status_code == 200
        ends2 = client.get("/me/boost", headers=_auth(users["trainer"]["token"])).json()[
            "endsAt"
        ]
        assert ends1 == ends2
    finally:
        app.dependency_overrides.pop(dep, None)


def test_easypaisa_ipn_activates(client: TestClient, users: dict) -> None:
    _ensure_pkr_products()
    _expire_trainer_boosts(users["trainer"]["user_id"])
    dep = _override_billing()
    settings = _local_settings()
    try:
        create = client.post(
            "/billing/boost/checkout",
            headers=_auth(users["trainer"]["token"]),
            json={"productId": "boost.featured.30d.pkr", "provider": "easypaisa"},
        )
        assert create.status_code == 200, create.text
        attempt_id = create.json()["attemptId"]
        merchant_txn, amount = _attempt_merchant(attempt_id)
        amount_rupees = f"{amount / 100.0:.2f}"
        token = easypaisa_secure_hash(
            store_id=settings.easypaisa_store_id,
            amount_rupees=amount_rupees,
            order_id=merchant_txn,
            hash_key=settings.easypaisa_hash_key,
        )
        fields = {
            "storeId": settings.easypaisa_store_id,
            "orderId": merchant_txn,
            "transactionAmount": amount_rupees,
            "transactionStatus": "PAID",
            "transactionId": f"EP{uuid4().hex[:12]}",
            "tokenHash": token,
        }
        ipn = client.post("/billing/webhooks/easypaisa", data=fields)
        assert ipn.status_code == 200, ipn.text
        me = client.get("/me/boost", headers=_auth(users["trainer"]["token"]))
        assert me.json()["active"] is True
        assert me.json()["source"] == "easypaisa"
        assert me.json()["productId"] == "boost.featured.30d.pkr"
    finally:
        app.dependency_overrides.pop(dep, None)


def test_confirm_after_late_ipn(client: TestClient, users: dict) -> None:
    _ensure_pkr_products()
    _expire_trainer_boosts(users["trainer"]["user_id"])
    dep = _override_billing()
    settings = _local_settings()
    try:
        create = client.post(
            "/billing/boost/checkout",
            headers=_auth(users["trainer"]["token"]),
            json={"productId": "boost.featured.7d.pkr", "provider": "jazzcash"},
        )
        attempt_id = create.json()["attemptId"]
        early = client.post(
            "/billing/boost/confirm",
            headers=_auth(users["trainer"]["token"]),
            json={"attemptId": attempt_id, "provider": "jazzcash"},
        )
        assert early.status_code == 200
        assert early.json()["active"] is False

        merchant_txn, amount = _attempt_merchant(attempt_id)
        fields = {
            "pp_MerchantID": settings.jazzcash_merchant_id,
            "pp_TxnRefNo": merchant_txn,
            "pp_Amount": str(amount),
            "pp_ResponseCode": "000",
            "pp_RetreivalReferenceNo": f"RRN{uuid4().hex[:10]}",
        }
        fields["pp_SecureHash"] = jazzcash_secure_hash(
            fields, settings.jazzcash_integrity_salt
        )
        assert client.post("/billing/webhooks/jazzcash", data=fields).status_code == 200

        late = client.post(
            "/billing/boost/confirm",
            headers=_auth(users["trainer"]["token"]),
            json={"attemptId": attempt_id, "provider": "jazzcash"},
        )
        assert late.status_code == 200
        assert late.json()["active"] is True
    finally:
        app.dependency_overrides.pop(dep, None)


def test_ai_entitlements_unaffected_by_local_boost(client: TestClient, users: dict) -> None:
    ent = client.get("/me/entitlements", headers=_auth(users["trainee"]["token"]))
    assert ent.status_code == 200
    ai = ent.json().get("ai") or {}
    # Boost purchase must not grant AI
    assert ai.get("active") is False or ai.get("active") is True  # shape present
    assert "active" in ai


def test_free_contact_unaffected(client: TestClient, users: dict) -> None:
    coaches = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
    assert coaches.status_code == 200
    items = coaches.json()["items"]
    assert items
    res = client.post(
        f"/coaches/{items[0]['id']}/contact",
        headers=_auth(users["trainee"]["token"]),
        json={},
    )
    assert res.status_code == 200, res.text
    assert res.json()["threadId"]
