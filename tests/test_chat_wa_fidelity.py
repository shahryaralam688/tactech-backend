"""WhatsApp-fidelity human chat: reply, delivered, read⇒delivered, played, react, edit, delete."""

from __future__ import annotations

from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


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
    trainer = _login(client, "trainer@tactech.app", settings.seed_trainer_password)
    trainee = _login(client, "trainee@tactech.app", settings.seed_trainee_password)
    return {"trainer": trainer, "trainee": trainee}


@pytest.fixture
def thread_id(client: TestClient, users: dict) -> str:
    create = client.post(
        "/chat/threads",
        headers=_auth(users["trainer"]["token"]),
        json={"peerUserId": users["trainee"]["user_id"]},
    )
    assert create.status_code in {200, 201}, create.text
    return create.json()["id"]


def test_reply_to_snapshot(client: TestClient, users: dict, thread_id: str) -> None:
    original = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
        json={"text": "Original quote me", "clientId": f"wa-orig-{uuid4().hex[:8]}"},
    )
    assert original.status_code == 201, original.text
    mid = original.json()["id"]

    reply = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainee"]["token"]),
        json={
            "text": "Replying",
            "clientId": f"wa-reply-{uuid4().hex[:8]}",
            "replyToMessageId": mid,
        },
    )
    assert reply.status_code == 201, reply.text
    body = reply.json()
    assert body["replyToMessageId"] == mid
    assert body["replyToText"] == "Original quote me"
    assert body["replyToSenderName"]

    bad = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainee"]["token"]),
        json={
            "text": "bad",
            "clientId": f"wa-bad-{uuid4().hex[:8]}",
            "replyToMessageId": "not-a-real-message",
        },
    )
    assert bad.status_code == 400
    assert bad.json().get("code") in {"VALIDATION", "VALIDATION_ERROR"}


def test_delivered_and_read_implies_delivered(
    client: TestClient, users: dict, thread_id: str
) -> None:
    send = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
        json={"text": "delivery tick", "clientId": f"wa-del-{uuid4().hex[:8]}"},
    )
    assert send.status_code == 201, send.text
    mid = send.json()["id"]
    assert send.json().get("deliveredAt") is None
    assert send.json().get("readAt") is None

    delivered = client.post(
        f"/chat/threads/{thread_id}/delivered",
        headers=_auth(users["trainee"]["token"]),
        json={"upToMessageId": mid},
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["deliveredByUserId"] == users["trainee"]["user_id"]

    listed = client.get(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
    )
    item = next(m for m in listed.json()["items"] if m["id"] == mid)
    assert item["deliveredAt"]
    assert item.get("readAt") is None

    # Second message: read without prior delivered → both set
    send2 = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
        json={"text": "read implies delivered", "clientId": f"wa-rd-{uuid4().hex[:8]}"},
    )
    mid2 = send2.json()["id"]
    read = client.post(
        f"/chat/threads/{thread_id}/read",
        headers=_auth(users["trainee"]["token"]),
        json={"upToMessageId": mid2},
    )
    assert read.status_code == 200
    listed2 = client.get(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
    )
    item2 = next(m for m in listed2.json()["items"] if m["id"] == mid2)
    assert item2["deliveredAt"]
    assert item2["readAt"]


def test_react_unreact_replace(client: TestClient, users: dict, thread_id: str) -> None:
    send = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
        json={"text": "react me", "clientId": f"wa-rx-{uuid4().hex[:8]}"},
    )
    mid = send.json()["id"]

    r1 = client.post(
        f"/chat/threads/{thread_id}/messages/{mid}/reactions",
        headers=_auth(users["trainee"]["token"]),
        json={"emoji": "👍"},
    )
    assert r1.status_code == 200, r1.text
    assert len(r1.json()["reactions"]) == 1
    assert r1.json()["reactions"][0]["emoji"] == "👍"

    r2 = client.post(
        f"/chat/threads/{thread_id}/messages/{mid}/reactions",
        headers=_auth(users["trainee"]["token"]),
        json={"emoji": "❤️"},
    )
    assert r2.status_code == 200
    emojis = [x["emoji"] for x in r2.json()["reactions"] if x["userId"] == users["trainee"]["user_id"]]
    assert emojis == ["❤️"]

    listed = client.get(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
    )
    item = next(m for m in listed.json()["items"] if m["id"] == mid)
    assert any(r["emoji"] == "❤️" for r in item["reactions"])

    deleted = client.delete(
        f"/chat/threads/{thread_id}/messages/{mid}/reactions/{quote('❤️')}",
        headers=_auth(users["trainee"]["token"]),
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["reactions"] == []


def test_edit_and_delete_everyone(client: TestClient, users: dict, thread_id: str) -> None:
    send = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
        json={"text": "typo messge", "clientId": f"wa-ed-{uuid4().hex[:8]}"},
    )
    mid = send.json()["id"]

    edited = client.patch(
        f"/chat/threads/{thread_id}/messages/{mid}",
        headers=_auth(users["trainer"]["token"]),
        json={"text": "typo message"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["text"] == "typo message"
    assert edited.json()["editedAt"]

    # Peer cannot edit
    forbidden = client.patch(
        f"/chat/threads/{thread_id}/messages/{mid}",
        headers=_auth(users["trainee"]["token"]),
        json={"text": "hijack"},
    )
    assert forbidden.status_code == 403

    deleted = client.delete(
        f"/chat/threads/{thread_id}/messages/{mid}?scope=everyone",
        headers=_auth(users["trainer"]["token"]),
    )
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["deletedForEveryoneAt"]
    assert body["text"] is None

    listed = client.get(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainee"]["token"]),
    )
    item = next(m for m in listed.json()["items"] if m["id"] == mid)
    assert item["deletedForEveryoneAt"]
    assert item["text"] is None


def test_client_id_idempotent(client: TestClient, users: dict, thread_id: str) -> None:
    cid = f"wa-idem-{uuid4().hex[:8]}"
    a = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
        json={"text": "once", "clientId": cid},
    )
    b = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
        json={"text": "once", "clientId": cid},
    )
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
