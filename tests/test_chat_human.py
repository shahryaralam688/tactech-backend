"""Human chat roster isolation + basic REST smoke."""

from __future__ import annotations

import io
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


def test_create_thread_and_text_roundtrip(client: TestClient, users: dict) -> None:
    # Trainer opens thread with trainee User.id
    create = client.post(
        "/chat/threads",
        headers=_auth(users["trainer"]["token"]),
        json={"peerUserId": users["trainee"]["user_id"]},
    )
    assert create.status_code in {200, 201}, create.text
    thread = create.json()
    assert thread["peerUserId"] == users["trainee"]["user_id"]
    assert thread["peerRole"] == "trainee"
    thread_id = thread["id"]

    send = client.post(
        "/chat/threads/{}/messages".format(thread_id),
        headers=_auth(users["trainer"]["token"]),
        json={"text": "See you at 5", "clientId": f"pytest-text-{uuid4().hex[:8]}"},
    )
    assert send.status_code == 201, send.text
    msg = send.json()
    assert msg["kind"] == "text"
    assert msg["text"] == "See you at 5"

    client_id = msg["clientId"]
    # Idempotent clientId
    again = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainer"]["token"]),
        json={"text": "See you at 5", "clientId": client_id},
    )
    assert again.status_code == 201
    assert again.json()["id"] == msg["id"]

    listed = client.get(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainee"]["token"]),
    )
    assert listed.status_code == 200
    ids = {m["id"] for m in listed.json()["items"]}
    assert msg["id"] in ids

    read = client.post(
        f"/chat/threads/{thread_id}/read",
        headers=_auth(users["trainee"]["token"]),
        json={"upToMessageId": msg["id"]},
    )
    assert read.status_code == 200
    assert read.json()["unreadCount"] == 0


def test_multipart_image(client: TestClient, users: dict) -> None:
    create = client.post(
        "/chat/threads",
        headers=_auth(users["trainer"]["token"]),
        json={"peerUserId": users["trainee"]["user_id"]},
    )
    thread_id = create.json()["id"]
    # Minimal 1x1 PNG
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    client_id = f"pytest-img-{uuid4().hex[:8]}"
    upload = client.post(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(users["trainee"]["token"]),
        files={"file": ("shot.png", io.BytesIO(png), "image/png")},
        data={"text": "form check", "clientId": client_id, "attachmentType": "image"},
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    assert body["kind"] == "attachment"
    assert body["attachmentType"] == "image"
    assert body["attachmentUrl"]
    assert body["attachmentUrl"].startswith("http")


def test_non_roster_forbidden(client: TestClient, users: dict) -> None:
    # Trainee cannot open a thread with a random user id
    resp = client.post(
        "/chat/threads",
        headers=_auth(users["trainee"]["token"]),
        json={"peerUserId": "does-not-exist-user"},
    )
    assert resp.status_code in {403, 404}


def test_rtc_incoming_ring_payload(client: TestClient, users: dict) -> None:
    create = client.post(
        "/chat/threads",
        headers=_auth(users["trainer"]["token"]),
        json={"peerUserId": users["trainee"]["user_id"]},
    )
    thread_id = create.json()["id"]
    rtc = client.post(
        "/chat/rtc/sessions",
        headers=_auth(users["trainer"]["token"]),
        json={"threadId": thread_id},
    )
    assert rtc.status_code == 201, rtc.text
    body = rtc.json()
    assert body["signalingPath"]
    assert body["id"] in body["signalingPath"]

    # Callee REST fallback sees the ringing session
    incoming = client.get("/chat/rtc/incoming", headers=_auth(users["trainee"]["token"]))
    assert incoming.status_code == 200, incoming.text
    items = incoming.json()["items"]
    assert any(row["sessionId"] == body["id"] for row in items)
    match = next(row for row in items if row["sessionId"] == body["id"])
    assert match["threadId"] == thread_id
    assert match["fromUserId"] == users["trainer"]["user_id"]
    assert match["fromName"]
    assert match["signalingPath"] == body["signalingPath"]

    # Caller should not see it as "incoming"
    caller_incoming = client.get("/chat/rtc/incoming", headers=_auth(users["trainer"]["token"]))
    assert caller_incoming.status_code == 200
    assert all(row["sessionId"] != body["id"] for row in caller_incoming.json()["items"])
