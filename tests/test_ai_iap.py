"""Phase 3 — Apple IAP AI entitlements + AI_REQUIRED gate."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.main import app
from app.services.ai_billing_service import AiBillingService
from app.services.billing.apple_iap import VerifiedAppleTransaction


def _jws(payload: dict[str, Any]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.sig"


class FakeApple:
    def __init__(self, *, bundle_id: str = "com.tactech.app") -> None:
        self.bundle_id = bundle_id
        self.by_id: dict[str, VerifiedAppleTransaction] = {}

    def configured(self) -> bool:
        return True

    def get_transaction(self, transaction_id: str) -> VerifiedAppleTransaction:
        tx = self.by_id.get(transaction_id)
        if tx is None:
            from app.core.exceptions import ValidationAppError

            raise ValidationAppError("Transaction not found in App Store.")
        return tx

    def verify_signed_transaction(self, signed_transaction: str) -> VerifiedAppleTransaction:
        from app.services.billing.apple_iap import decode_jws_payload, transaction_from_payload

        payload = decode_jws_payload(signed_transaction)
        tx = transaction_from_payload(payload)
        self.by_id[tx.transaction_id] = tx
        return tx

    def decode_notification(self, signed_payload: str) -> dict[str, Any]:
        from app.services.billing.apple_iap import decode_jws_payload

        return decode_jws_payload(signed_payload)

    def put(
        self,
        *,
        transaction_id: str,
        original_transaction_id: str,
        product_id: str = "ai.pro.monthly",
        days: int = 30,
        revoked: bool = False,
    ) -> VerifiedAppleTransaction:
        now = datetime.now(timezone.utc)
        tx = VerifiedAppleTransaction(
            transaction_id=transaction_id,
            original_transaction_id=original_transaction_id,
            product_id=product_id,
            bundle_id=self.bundle_id,
            environment="Sandbox",
            purchase_date=now,
            expires_date=now + timedelta(days=days),
            revocation_date=now if revoked else None,
            type="Auto-Renewable Subscription",
            raw={
                "transactionId": transaction_id,
                "originalTransactionId": original_transaction_id,
                "productId": product_id,
                "bundleId": self.bundle_id,
                "environment": "Sandbox",
                "purchaseDate": int(now.timestamp() * 1000),
                "expiresDate": int((now + timedelta(days=days)).timestamp() * 1000),
            },
        )
        self.by_id[transaction_id] = tx
        return tx


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"token": body["accessToken"], "user_id": body["user"]["id"]}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def users(client: TestClient) -> dict:
    settings = get_settings()
    return {
        "trainee": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
        "trainee2": _login(client, "priya@tactech.app", settings.seed_trainee_password),
        "trainer": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
        "settings": settings,
    }


@pytest.fixture()
def fake_apple(monkeypatch: pytest.MonkeyPatch) -> FakeApple:
    fake = FakeApple(bundle_id="com.tactech.app")
    settings = get_settings()
    # Force bundle match in verify
    object.__setattr__(settings, "apple_bundle_id", "com.tactech.app")
    get_settings.cache_clear()
    from app.api.deps import get_ai_billing_service

    def override():
        db = SessionLocal()
        try:
            s = get_settings()
            object.__setattr__(s, "apple_bundle_id", "com.tactech.app")
            yield AiBillingService(db, s, apple=fake)
        finally:
            db.close()

    app.dependency_overrides[get_ai_billing_service] = override
    yield fake
    app.dependency_overrides.pop(get_ai_billing_service, None)
    get_settings.cache_clear()


def _clear_ai(user_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.scalars(select(models.AiEntitlement).where(models.AiEntitlement.user_id == user_id)).first()
        if row:
            db.delete(row)
            db.commit()
    finally:
        db.close()


def test_ai_products_list(client: TestClient, users: dict) -> None:
    res = client.get("/billing/products?type=ai", headers=_auth(users["trainee"]["token"]))
    assert res.status_code == 200, res.text
    ids = {i["id"] for i in res.json()["items"]}
    assert "ai.pro.monthly" in ids
    for item in res.json()["items"]:
        assert item["appleProductId"]
        assert item["type"] == "ai"


def test_verify_activates_and_entitlements_agree(
    client: TestClient, users: dict, fake_apple: FakeApple
) -> None:
    _clear_ai(users["trainee"]["user_id"])
    tid = f"tx_{uuid4().hex[:12]}"
    otid = f"ot_{uuid4().hex[:12]}"
    fake_apple.put(transaction_id=tid, original_transaction_id=otid)
    signed = _jws(fake_apple.by_id[tid].raw or {})

    verify = client.post(
        "/billing/ai/apple/verify",
        headers=_auth(users["trainee"]["token"]),
        json={"signedTransaction": signed},
    )
    assert verify.status_code == 200, verify.text
    body = verify.json()
    assert body["active"] is True
    assert body["source"] == "apple"
    assert body["plan"]

    me_ai = client.get("/me/ai", headers=_auth(users["trainee"]["token"]))
    assert me_ai.json()["active"] is True

    ent = client.get("/me/entitlements", headers=_auth(users["trainee"]["token"]))
    assert ent.status_code == 200
    assert ent.json()["ai"]["active"] is True
    assert ent.json()["ai"]["source"] == "apple"
    # Boost slice still present (Phase 2)
    assert "boost" in ent.json()


def test_wrong_bundle_and_unknown_product(
    client: TestClient, users: dict, fake_apple: FakeApple
) -> None:
    _clear_ai(users["trainee"]["user_id"])
    tid = f"tx_{uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    bad_bundle = {
        "transactionId": tid,
        "originalTransactionId": tid,
        "productId": "ai.pro.monthly",
        "bundleId": "com.other.app",
        "environment": "Sandbox",
        "purchaseDate": int(now.timestamp() * 1000),
        "expiresDate": int((now + timedelta(days=30)).timestamp() * 1000),
    }
    r = client.post(
        "/billing/ai/apple/verify",
        headers=_auth(users["trainee"]["token"]),
        json={"signedTransaction": _jws(bad_bundle)},
    )
    assert r.status_code == 400

    unknown = dict(bad_bundle)
    unknown["bundleId"] = "com.tactech.app"
    unknown["productId"] = "ai.unknown"
    unknown["transactionId"] = f"tx_{uuid4().hex[:12]}"
    unknown["originalTransactionId"] = unknown["transactionId"]
    r2 = client.post(
        "/billing/ai/apple/verify",
        headers=_auth(users["trainee"]["token"]),
        json={"signedTransaction": _jws(unknown)},
    )
    assert r2.status_code == 400


def test_storekit_placeholder_tx_id_zero_no_cross_account_409(
    client: TestClient, users: dict, fake_apple: FakeApple
) -> None:
    """Xcode StoreKit Testing often sends transactionId=0 — must not 409 across users."""
    _clear_ai(users["trainee"]["user_id"])
    _clear_ai(users["trainee2"]["user_id"])
    now = datetime.now(timezone.utc)
    payload = {
        "transactionId": "0",
        "originalTransactionId": "0",
        "productId": "ai.pro.monthly",
        "bundleId": "com.tactech.app",
        "environment": "Sandbox",
        "purchaseDate": int(now.timestamp() * 1000),
        "expiresDate": int((now + timedelta(days=30)).timestamp() * 1000),
    }
    signed = _jws(payload)

    r1 = client.post(
        "/billing/ai/apple/verify",
        headers=_auth(users["trainee"]["token"]),
        json={"signedTransaction": signed},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["active"] is True

    r2 = client.post(
        "/billing/ai/apple/verify",
        headers=_auth(users["trainee2"]["token"]),
        json={"signedTransaction": signed},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["active"] is True


def test_original_transaction_conflict_409(
    client: TestClient, users: dict, fake_apple: FakeApple
) -> None:
    _clear_ai(users["trainee"]["user_id"])
    _clear_ai(users["trainee2"]["user_id"])
    tid = f"tx_{uuid4().hex[:12]}"
    otid = f"ot_{uuid4().hex[:12]}"
    fake_apple.put(transaction_id=tid, original_transaction_id=otid)
    signed = _jws(fake_apple.by_id[tid].raw or {})

    assert (
        client.post(
            "/billing/ai/apple/verify",
            headers=_auth(users["trainee"]["token"]),
            json={"signedTransaction": signed},
        ).status_code
        == 200
    )

    # Same original to another user → 409 (new transaction id, same original)
    tid2 = f"tx_{uuid4().hex[:12]}"
    fake_apple.put(transaction_id=tid2, original_transaction_id=otid)
    signed2 = _jws(fake_apple.by_id[tid2].raw or {})
    conflict = client.post(
        "/billing/ai/apple/verify",
        headers=_auth(users["trainee2"]["token"]),
        json={"signedTransaction": signed2},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CONFLICT"


def test_duplicate_verify_idempotent(
    client: TestClient, users: dict, fake_apple: FakeApple
) -> None:
    _clear_ai(users["trainee"]["user_id"])
    tid = f"tx_{uuid4().hex[:12]}"
    otid = f"ot_{uuid4().hex[:12]}"
    fake_apple.put(transaction_id=tid, original_transaction_id=otid)
    signed = _jws(fake_apple.by_id[tid].raw or {})
    h = _auth(users["trainee"]["token"])
    assert client.post("/billing/ai/apple/verify", headers=h, json={"signedTransaction": signed}).status_code == 200
    again = client.post("/billing/ai/apple/verify", headers=h, json={"signedTransaction": signed})
    assert again.status_code == 200
    assert again.json()["active"] is True


def test_assn_expired_turns_inactive(
    client: TestClient, users: dict, fake_apple: FakeApple
) -> None:
    _clear_ai(users["trainee"]["user_id"])
    tid = f"tx_{uuid4().hex[:12]}"
    otid = f"ot_{uuid4().hex[:12]}"
    fake_apple.put(transaction_id=tid, original_transaction_id=otid)
    signed = _jws(fake_apple.by_id[tid].raw or {})
    assert (
        client.post(
            "/billing/ai/apple/verify",
            headers=_auth(users["trainee"]["token"]),
            json={"signedTransaction": signed},
        ).status_code
        == 200
    )

    notif = {
        "notificationType": "EXPIRED",
        "notificationUUID": str(uuid4()),
        "data": {"signedTransactionInfo": signed},
    }
    r = client.post("/billing/webhooks/apple", content=json.dumps({"signedPayload": _jws(notif)}))
    # Outer body is JSON with signedPayload which is itself JWS of notification
    assert r.status_code == 200, r.text

    me = client.get("/me/ai", headers=_auth(users["trainee"]["token"]))
    assert me.json()["active"] is False


def test_ai_chat_402_without_entitlement(client: TestClient, users: dict) -> None:
    _clear_ai(users["trainee"]["user_id"])
    # Ensure hard paywall on cached settings instance (no daily free + no weekly tease)
    object.__setattr__(get_settings(), "ai_free_tease_messages_per_week", 0)
    object.__setattr__(get_settings(), "ai_free_chat_daily_limit", 0)

    res = client.post(
        "/coach/chat",
        headers=_auth(users["trainee"]["token"]),
        json={"message": "hi", "stream": False},
    )
    assert res.status_code == 402, res.text
    body = res.json()
    assert body["code"] == "AI_REQUIRED"
    assert body["action"] == "subscribe"
    assert body["productHint"] == "ai.pro.monthly"
    assert "AI Coach Pro" in body["detail"]

    # Conversations still open
    conv = client.post("/coach/conversations", headers=_auth(users["trainee"]["token"]))
    assert conv.status_code == 201

    # Human chat / coaches still work
    coaches = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
    assert coaches.status_code == 200


def test_ai_chat_works_with_entitlement(client: TestClient, users: dict) -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        AiBillingService(db, settings).grant_manual(
            user_id=users["trainee"]["user_id"], days=7
        )
    finally:
        db.close()

    res = client.post(
        "/coach/chat",
        headers=_auth(users["trainee"]["token"]),
        json={"message": "hello coach", "stream": False},
    )
    assert res.status_code == 200, res.text


def test_boost_and_contact_unbroken(client: TestClient, users: dict) -> None:
    products = client.get("/billing/products?type=boost", headers=_auth(users["trainer"]["token"]))
    assert products.status_code == 200
    assert any(i["type"] == "boost" for i in products.json()["items"])

    coaches = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
    assert coaches.status_code == 200
    if coaches.json()["items"]:
        cid = coaches.json()["items"][0]["id"]
        contact = client.post(
            f"/coaches/{cid}/contact",
            headers=_auth(users["trainee"]["token"]),
            json={},
        )
        assert contact.status_code == 200
