"""Cross-user isolation for AI Coach conversations.

Policy:
- Unknown conversation id → 404 NOT_FOUND ("Chat not found.")
- Exists but owned by another user → 403 FORBIDDEN ("You can’t access this chat.")
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token = response.json().get("accessToken")
    assert token
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def tokens(client: TestClient) -> dict[str, str]:
    settings = get_settings()
    return {
        "a": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
        "b": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
    }


@pytest.fixture(scope="module")
def conversations(client: TestClient, tokens: dict[str, str]) -> dict[str, str]:
    """Create cA for user A and cB for user B with a secret message each."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.db import models
    from app.db.session import SessionLocal
    from app.services.ai_billing_service import AiBillingService

    # Phase 3: AI generate routes require entitlement — grant for isolation tests.
    settings = get_settings()
    db = SessionLocal()
    try:
        svc = AiBillingService(db, settings)
        for email in ("trainer@tactech.app", "trainee@tactech.app"):
            user = db.scalars(select(models.User).where(models.User.email == email)).first()
            assert user
            svc.grant_manual(user_id=user.id, product_id="ai.pro.monthly", days=30)
    finally:
        db.close()

    # User A
    ca = client.post("/coach/conversations", headers=_auth(tokens["a"]))
    assert ca.status_code == 201, ca.text
    c_a = ca.json()["id"]
    send_a = client.post(
        "/coach/chat",
        headers=_auth(tokens["a"]),
        json={"message": "secret from A", "conversationId": c_a, "stream": False},
    )
    assert send_a.status_code == 200, send_a.text
    assert "secret from A" in send_a.json()["userMessage"]["content"]

    # User B
    cb = client.post("/coach/conversations", headers=_auth(tokens["b"]))
    assert cb.status_code == 201, cb.text
    c_b = cb.json()["id"]
    send_b = client.post(
        "/coach/chat",
        headers=_auth(tokens["b"]),
        json={"message": "secret from B", "conversationId": c_b, "stream": False},
    )
    assert send_b.status_code == 200, send_b.text
    assert "secret from B" in send_b.json()["userMessage"]["content"]

    return {"cA": c_a, "cB": c_b}


def test_list_only_own_conversations(client: TestClient, tokens: dict[str, str], conversations: dict[str, str]) -> None:
    list_a = client.get("/coach/conversations", headers=_auth(tokens["a"]))
    assert list_a.status_code == 200
    ids_a = {row["id"] for row in list_a.json()}
    assert conversations["cA"] in ids_a
    assert conversations["cB"] not in ids_a

    list_b = client.get("/coach/conversations", headers=_auth(tokens["b"]))
    assert list_b.status_code == 200
    ids_b = {row["id"] for row in list_b.json()}
    assert conversations["cB"] in ids_b
    assert conversations["cA"] not in ids_b


def test_cannot_read_other_user_messages(
    client: TestClient, tokens: dict[str, str], conversations: dict[str, str]
) -> None:
    response = client.get(
        f"/coach/conversations/{conversations['cB']}/messages",
        headers=_auth(tokens["a"]),
    )
    assert response.status_code == 403
    body = response.json()
    assert body.get("code") == "FORBIDDEN"
    assert "secret from B" not in response.text


def test_cannot_chat_into_other_user_conversation(
    client: TestClient, tokens: dict[str, str], conversations: dict[str, str]
) -> None:
    before = client.get(
        f"/coach/conversations/{conversations['cB']}/messages",
        headers=_auth(tokens["b"]),
    )
    assert before.status_code == 200
    count_before = len(before.json())

    response = client.post(
        "/coach/chat",
        headers=_auth(tokens["a"]),
        json={
            "message": "intrusion attempt",
            "conversationId": conversations["cB"],
            "stream": False,
        },
    )
    assert response.status_code == 403
    assert response.json().get("code") == "FORBIDDEN"
    assert "secret from B" not in response.text
    assert "intrusion" not in response.text.lower()

    after = client.get(
        f"/coach/conversations/{conversations['cB']}/messages",
        headers=_auth(tokens["b"]),
    )
    assert after.status_code == 200
    assert len(after.json()) == count_before
    assert all("intrusion" not in (m.get("content") or "").lower() for m in after.json())


def test_cannot_delete_other_user_conversation(
    client: TestClient, tokens: dict[str, str], conversations: dict[str, str]
) -> None:
    response = client.delete(
        f"/coach/conversations/{conversations['cB']}",
        headers=_auth(tokens["a"]),
    )
    assert response.status_code == 403
    assert response.json().get("code") == "FORBIDDEN"

    still = client.get("/coach/conversations", headers=_auth(tokens["b"]))
    assert still.status_code == 200
    assert conversations["cB"] in {row["id"] for row in still.json()}

    msgs = client.get(
        f"/coach/conversations/{conversations['cB']}/messages",
        headers=_auth(tokens["b"]),
    )
    assert msgs.status_code == 200
    assert any("secret from B" in (m.get("content") or "") for m in msgs.json())


def test_unknown_conversation_is_404(client: TestClient, tokens: dict[str, str]) -> None:
    response = client.get(
        "/coach/conversations/does-not-exist/messages",
        headers=_auth(tokens["a"]),
    )
    assert response.status_code == 404
    assert response.json().get("code") == "NOT_FOUND"


def test_rtc_session_rejects_foreign_conversation(
    client: TestClient, tokens: dict[str, str], conversations: dict[str, str]
) -> None:
    response = client.post(
        f"/coach/rtc/sessions?conversationId={conversations['cB']}",
        headers=_auth(tokens["a"]),
    )
    assert response.status_code == 403
    assert response.json().get("code") == "FORBIDDEN"


def test_memory_sync_scoped_to_caller(client: TestClient, tokens: dict[str, str]) -> None:
    response = client.post("/coach/memory/sync", headers=_auth(tokens["a"]))
    assert response.status_code == 200
    body = response.json()
    # CamelCase: userId must be the JWT subject for A (trainer maya)
    assert body.get("userId") == "user-trainer-maya"
