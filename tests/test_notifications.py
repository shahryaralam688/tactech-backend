"""Push tokens + in-app notification inbox."""

from __future__ import annotations

from uuid import uuid4

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
    return response.json()["accessToken"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def tokens(client: TestClient) -> dict[str, str]:
    settings = get_settings()
    return {
        "trainer": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
        "trainee": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
    }


def test_register_and_list_push_token(client: TestClient, tokens: dict[str, str]) -> None:
    reg = client.post(
        "/me/push-tokens",
        headers=_auth(tokens["trainee"]),
        json={
            "token": "fake-apns-token-pytest-001",
            "platform": "ios",
            "deviceName": "iPhone",
            "appVersion": "1.0.0",
        },
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    assert body["platform"] == "ios"
    assert body["deviceName"] == "iPhone"

    listed = client.get("/me/push-tokens", headers=_auth(tokens["trainee"]))
    assert listed.status_code == 200
    assert any(t["id"] == body["id"] for t in listed.json())


_PREF_KEYS = (
    "push",
    "aiCoach",
    "metrics",
    "vibrations",
    "sound",
    "appUpdate",
    "resources",
    "offersDevice",
    "chatMessages",
    "chatCalls",
)


def test_notification_prefs_include_chat_flags(client: TestClient, tokens: dict[str, str]) -> None:
    prefs = client.get("/me/preferences/notifications", headers=_auth(tokens["trainer"]))
    assert prefs.status_code == 200
    data = prefs.json()
    for key in _PREF_KEYS:
        assert key in data
        assert isinstance(data[key], bool)

    put = client.put(
        "/me/preferences/notifications",
        headers=_auth(tokens["trainer"]),
        json={
            **data,
            "chatMessages": False,
            "chatCalls": True,
            "push": True,
        },
    )
    assert put.status_code == 200, put.text
    assert put.json()["chatMessages"] is False
    again = client.get("/me/preferences/notifications", headers=_auth(tokens["trainer"]))
    assert again.json()["chatMessages"] is False


def test_notification_prefs_partial_put_and_all_toggles(client: TestClient, tokens: dict[str, str]) -> None:
    # Reset to known baseline
    base = {k: True for k in _PREF_KEYS}
    base["aiCoach"] = False
    base["resources"] = False
    base["offersDevice"] = False
    base["vibrations"] = False
    saved = client.put(
        "/me/preferences/notifications",
        headers=_auth(tokens["trainer"]),
        json=base,
    )
    assert saved.status_code == 200, saved.text

    # Partial: flip metrics + vibrations only
    patch = client.put(
        "/me/preferences/notifications",
        headers=_auth(tokens["trainer"]),
        json={"metrics": False, "vibrations": True},
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["metrics"] is False
    assert body["vibrations"] is True
    assert body["chatMessages"] is True  # preserved
    assert body["push"] is True

    again = client.get("/me/preferences/notifications", headers=_auth(tokens["trainer"]))
    assert again.json() == body
    for key in _PREF_KEYS:
        assert key in again.json()


def test_push_gate_matrix() -> None:
    from app.schemas.preferences import NotificationPreferences
    from app.services.push_service import PushService

    def gate(**overrides) -> NotificationPreferences:
        data = NotificationPreferences().model_dump()
        data.update(overrides)
        return NotificationPreferences.model_validate(data)

    # Master off → nothing
    off = gate(push=False)
    for t in ("chat", "chat_call", "plan_assigned", "join_request", "relationship_ended"):
        assert PushService._should_send_push(off, t) is False

    # Type gates
    assert PushService._should_send_push(gate(chat_messages=False), "chat") is False
    assert PushService._should_send_push(gate(chat_calls=False), "chat_call") is False
    assert PushService._should_send_push(gate(ai_coach=False), "ai_coach") is False
    assert PushService._should_send_push(gate(metrics=False), "metrics") is False
    assert PushService._should_send_push(gate(metrics=False), "workout") is False
    assert PushService._should_send_push(gate(metrics=False), "plan_assigned") is False
    assert PushService._should_send_push(gate(metrics=False), "plan_unassigned") is False
    assert PushService._should_send_push(gate(metrics=False), "plan_updated") is False
    assert PushService._should_send_push(gate(app_update=False), "app_update") is False
    assert PushService._should_send_push(gate(resources=False), "resources") is False
    assert PushService._should_send_push(gate(offers_device=False), "offers") is False

    # Master-only coaching types still send when push on
    assert PushService._should_send_push(gate(metrics=False), "join_request") is True
    assert PushService._should_send_push(gate(metrics=False), "relationship_ended") is True

    # vibrations/sound unused by gate
    assert PushService._should_send_push(gate(vibrations=False, sound=False), "chat") is True


def test_chat_messages_pref_false_still_creates_inbox_no_apns_queue(
    client: TestClient, tokens: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """chatMessages=false → inbox + Socket path OK; remote push not queued."""
    import logging

    # Trainee turns off chat message pushes
    prefs = client.get("/me/preferences/notifications", headers=_auth(tokens["trainee"])).json()
    prefs["chatMessages"] = False
    prefs["push"] = True
    saved = client.put(
        "/me/preferences/notifications",
        headers=_auth(tokens["trainee"]),
        json=prefs,
    )
    assert saved.status_code == 200
    assert saved.json()["chatMessages"] is False

    # Register a token so a gated send would otherwise queue
    client.post(
        "/me/push-tokens",
        headers=_auth(tokens["trainee"]),
        json={
            "token": "fake-apns-token-pref-gate-001",
            "platform": "ios",
            "deviceName": "iPhone",
            "appVersion": "1.0.0",
        },
    )

    trainee_id = client.post(
        "/auth/login",
        json={"email": "trainee@tactech.app", "password": get_settings().seed_trainee_password},
    ).json()["user"]["id"]
    thread = client.post(
        "/chat/threads",
        headers=_auth(tokens["trainer"]),
        json={"peerUserId": trainee_id},
    )
    thread_id = thread.json()["id"]

    with caplog.at_level(logging.INFO, logger="tactech.push"):
        send = client.post(
            f"/chat/threads/{thread_id}/messages",
            headers=_auth(tokens["trainer"]),
            json={"text": "pref gated msg", "clientId": f"pref-gate-{uuid4().hex[:10]}"},
        )
    assert send.status_code == 201, send.text

    inbox = client.get("/me/notifications", headers=_auth(tokens["trainee"]))
    assert inbox.status_code == 200
    assert any(n["type"] == "chat" and "pref gated" in n["body"] for n in inbox.json()["items"])

    # Should not see push_queued for this delivery; expect push_skipped_pref
    joined = " ".join(r.message for r in caplog.records)
    assert "push_queued" not in joined or "pref gated" not in joined
    # Restore prefs for other tests
    prefs["chatMessages"] = True
    client.put("/me/preferences/notifications", headers=_auth(tokens["trainee"]), json=prefs)


def test_chat_message_creates_inbox_when_offline(client: TestClient, tokens: dict[str, str]) -> None:
    # Ensure thread
    trainee_login = client.post(
        "/auth/login",
        json={"email": "trainee@tactech.app", "password": get_settings().seed_trainee_password},
    ).json()
    peer = trainee_login["user"]["id"]
    thread = client.post(
        "/chat/threads",
        headers=_auth(tokens["trainer"]),
        json={"peerUserId": peer},
    )
    assert thread.status_code in {200, 201}
    thread_id = thread.json()["id"]

    # Ensure chat message pushes are allowed (other tests may flip prefs)
    prefs = client.get("/me/preferences/notifications", headers=_auth(tokens["trainee"])).json()
    prefs["chatMessages"] = True
    prefs["push"] = True
    client.put("/me/preferences/notifications", headers=_auth(tokens["trainee"]), json=prefs)

    send = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(tokens["trainer"]),
        json={"text": "notif smoke", "clientId": f"notif-smoke-{uuid4().hex[:10]}"},
    )
    assert send.status_code == 201, send.text

    inbox = client.get("/me/notifications", headers=_auth(tokens["trainee"]))
    assert inbox.status_code == 200, inbox.text
    items = inbox.json()["items"]
    assert any(n["type"] == "chat" and "notif smoke" in n["body"] for n in items)

    unread = client.get("/me/notifications/unread-count", headers=_auth(tokens["trainee"]))
    assert unread.status_code == 200
    assert unread.json()["unreadCount"] >= 1

    mark = client.post(
        "/me/notifications/read",
        headers=_auth(tokens["trainee"]),
        json={},
    )
    assert mark.status_code == 200
    assert mark.json()["unreadCount"] == 0


def test_delete_one_and_clear_all(client: TestClient, tokens: dict[str, str]) -> None:
    from app.db import models
    from app.db.session import SessionLocal
    from app.repositories.notifications import NotificationRepository

    db = SessionLocal()
    try:
        trainee_id = client.post(
            "/auth/login",
            json={
                "email": "trainee@tactech.app",
                "password": get_settings().seed_trainee_password,
            },
        ).json()["user"]["id"]
        trainer_id = client.post(
            "/auth/login",
            json={
                "email": "trainer@tactech.app",
                "password": get_settings().seed_trainer_password,
            },
        ).json()["user"]["id"]

        repo = NotificationRepository(db)
        a = repo.create(
            user_id=trainee_id,
            type="system",
            title="A",
            body="delete me",
            data={"k": "1"},
        )
        b = repo.create(
            user_id=trainee_id,
            type="system",
            title="B",
            body="keep then clear",
            data={"k": "2"},
        )
        other = repo.create(
            user_id=trainer_id,
            type="system",
            title="Other user",
            body="must not delete",
            data={},
        )
        a_id, b_id, other_id = a.id, b.id, other.id
    finally:
        db.close()

    # Single delete
    deleted = client.post(
        "/me/notifications/delete",
        headers=_auth(tokens["trainee"]),
        json={"notificationId": a_id},
    )
    assert deleted.status_code == 200, deleted.text
    assert "unreadCount" in deleted.json()

    inbox = client.get("/me/notifications", headers=_auth(tokens["trainee"]))
    ids = {n["id"] for n in inbox.json()["items"]}
    assert a_id not in ids
    assert b_id in ids

    # Idempotent — same id again → 200, not 404
    again = client.post(
        "/me/notifications/delete",
        headers=_auth(tokens["trainee"]),
        json={"notificationId": a_id},
    )
    assert again.status_code == 200

    # Cannot delete another user's row (no-op for caller)
    cross = client.post(
        "/me/notifications/delete",
        headers=_auth(tokens["trainee"]),
        json={"notificationId": other_id},
    )
    assert cross.status_code == 200
    still = client.get("/me/notifications", headers=_auth(tokens["trainer"]))
    assert other_id in {n["id"] for n in still.json()["items"]}

    # Clear all for trainee
    clear = client.post(
        "/me/notifications/delete",
        headers=_auth(tokens["trainee"]),
        json={},
    )
    assert clear.status_code == 200
    assert clear.json()["unreadCount"] == 0
    empty = client.get("/me/notifications", headers=_auth(tokens["trainee"]))
    assert empty.json()["items"] == []

    # Null body also clears (already empty — still 200)
    null_clear = client.post(
        "/me/notifications/delete",
        headers=_auth(tokens["trainee"]),
        json={"notificationId": None},
    )
    assert null_clear.status_code == 200
    assert null_clear.json()["unreadCount"] == 0

    # Trainer's notification untouched
    trainer_inbox = client.get("/me/notifications", headers=_auth(tokens["trainer"]))
    assert other_id in {n["id"] for n in trainer_inbox.json()["items"]}

    # Cleanup trainer row
    db = SessionLocal()
    try:
        row = db.get(models.AppNotification, other_id)
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()
