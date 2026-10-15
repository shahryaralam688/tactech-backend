"""Invite → pending join request → accept / reject / cancel."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    body = res.json()
    return {
        "token": body["accessToken"],
        "user_id": body["user"]["id"],
        "role": body["user"]["role"],
        "trainer_id": (body.get("trainer") or {}).get("id"),
        "trainee_id": (body.get("trainee") or {}).get("id"),
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _flush_redis() -> None:
    from app.core.redis import create_redis_client

    r = create_redis_client()
    try:
        r.flushdb()
    finally:
        r.close()


def _signup_trainee(client: TestClient, *, invite_code: str | None = None) -> dict:
    _flush_redis()
    email = f"jr.{uuid4().hex[:10]}@tactech.app"
    payload: dict = {
        "name": "Join QA",
        "email": email,
        "password": "JoinTest1!",
        "role": "trainee",
    }
    if invite_code:
        payload["inviteCode"] = invite_code
    res = client.post("/auth/signup", json=payload)
    assert res.status_code in (200, 201), res.text
    body = res.json()
    return {
        "token": body["accessToken"],
        "user_id": body["user"]["id"],
        "trainee_id": (body.get("trainee") or {}).get("id"),
        "email": email,
    }


@pytest.fixture(scope="module")
def actors(client: TestClient) -> dict:
    _flush_redis()
    settings = get_settings()
    return {
        "maya": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
        "ali": _login(client, "ali.coach@tactech.app", settings.seed_trainer_password),
        "omar": _login(client, "omar.coach@tactech.app", settings.seed_trainer_password),
    }


def _roster_ids(roster_json: list) -> set[str]:
    return {t["id"] for t in roster_json}


def _inbox_types(client: TestClient, token: str) -> list[str]:
    inbox = client.get("/me/notifications", headers=_auth(token))
    assert inbox.status_code == 200, inbox.text
    return [n["type"] for n in inbox.json()["items"]]


def test_create_pending_not_on_roster(client: TestClient, actors: dict) -> None:
    a = _signup_trainee(client)
    create = client.post(
        "/trainee/join-requests",
        headers=_auth(a["token"]),
        json={"inviteCode": "TACT-OMAR", "message": "Hi — evenings"},
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["status"] == "pending"
    assert body["inviteCode"] == "TACT-OMAR"
    assert body["message"] == "Hi — evenings"
    assert body["trainer"]["id"] == actors["omar"]["user_id"]

    mine = client.get("/trainee/join-requests/mine", headers=_auth(a["token"]))
    assert mine.status_code == 200
    assert mine.json()["pendingRequest"]["id"] == body["id"]
    assert mine.json()["activeLink"] is None

    trainer = client.get("/trainee/trainer", headers=_auth(a["token"]))
    assert trainer.status_code == 200
    assert trainer.json() is None

    roster = client.get("/trainer/trainees", headers=_auth(actors["omar"]["token"]))
    assert a["trainee_id"] not in _roster_ids(roster.json())

    # Trainer must see inbox + pending list immediately (hotfix)
    inbox = client.get("/me/notifications", headers=_auth(actors["omar"]["token"]))
    assert inbox.status_code == 200
    jr_notifs = [n for n in inbox.json()["items"] if n["type"] == "join_request"]
    assert jr_notifs, "trainer inbox missing join_request"
    latest = jr_notifs[0]
    assert latest["title"] == "New trainee request"
    assert latest["data"].get("joinRequestId") == body["id"]
    assert latest["data"].get("type") == "join_request"
    assert latest["data"].get("traineeUserId") == a["user_id"]
    assert latest.get("readAt") is None

    listed = client.get(
        "/trainer/join-requests?status=pending",
        headers=_auth(actors["omar"]["token"]),
    )
    assert listed.status_code == 200
    assert any(r["id"] == body["id"] for r in listed.json())
    match = next(r for r in listed.json() if r["id"] == body["id"])
    assert match["trainee"]["id"] == a["user_id"]
    assert match["trainee"]["name"]


def test_accept_activates_roster(client: TestClient, actors: dict) -> None:
    a = _signup_trainee(client)
    create = client.post(
        "/trainee/join-requests",
        headers=_auth(a["token"]),
        json={"inviteCode": "TACT-OMAR"},
    )
    assert create.status_code == 201, create.text
    jr_id = create.json()["id"]

    accept = client.post(
        f"/trainer/join-requests/{jr_id}/accept",
        headers=_auth(actors["omar"]["token"]),
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == "accepted"
    assert accept.json()["trainee"]["id"] == a["user_id"]

    roster = client.get("/trainer/trainees", headers=_auth(actors["omar"]["token"]))
    assert a["trainee_id"] in _roster_ids(roster.json())

    me = client.get("/trainee/trainer", headers=_auth(a["token"]))
    assert me.status_code == 200
    assert me.json() is not None
    assert me.json()["trainer"]["inviteCode"] == "TACT-OMAR"

    mine = client.get("/trainee/join-requests/mine", headers=_auth(a["token"]))
    assert mine.json()["pendingRequest"] is None
    assert mine.json()["activeLink"]["trainerId"] == actors["omar"]["user_id"]

    inbox = client.get("/me/notifications", headers=_auth(a["token"]))
    accepted = [n for n in inbox.json()["items"] if n["type"] == "join_request_accepted"]
    assert accepted, "trainee inbox missing join_request_accepted"
    assert accepted[0]["data"].get("joinRequestId") == jr_id
    assert accepted[0]["data"].get("type") == "join_request_accepted"


def test_reject_no_roster_can_request_again(client: TestClient, actors: dict) -> None:
    b = _signup_trainee(client)
    create = client.post(
        "/trainee/join-requests",
        headers=_auth(b["token"]),
        json={"inviteCode": "TACT-OMAR"},
    )
    jr_id = create.json()["id"]

    reject = client.post(
        f"/trainer/join-requests/{jr_id}/reject",
        headers=_auth(actors["omar"]["token"]),
        json={"reason": "Roster full"},
    )
    assert reject.status_code == 200, reject.text
    assert reject.json()["status"] == "rejected"

    roster = client.get("/trainer/trainees", headers=_auth(actors["omar"]["token"]))
    assert b["trainee_id"] not in _roster_ids(roster.json())

    # Trainee Pending must clear + durable inbox for live UI
    mine = client.get("/trainee/join-requests/mine", headers=_auth(b["token"]))
    assert mine.status_code == 200
    assert mine.json()["pendingRequest"] is None
    assert mine.json()["activeLink"] is None

    inbox = client.get("/me/notifications", headers=_auth(b["token"]))
    assert inbox.status_code == 200
    rejected = [n for n in inbox.json()["items"] if n["type"] == "join_request_rejected"]
    assert rejected, "trainee inbox missing join_request_rejected"
    assert rejected[0]["title"] == "Request declined"
    assert rejected[0]["data"].get("joinRequestId") == jr_id
    assert rejected[0]["data"].get("type") == "join_request_rejected"
    assert rejected[0]["data"].get("trainerUserId") == actors["omar"]["user_id"]

    again = client.post(
        "/trainee/join-requests",
        headers=_auth(b["token"]),
        json={"inviteCode": "TACT-OMAR"},
    )
    assert again.status_code == 201, again.text


def test_cancel_then_create_again(client: TestClient, actors: dict) -> None:
    t = _signup_trainee(client)
    create = client.post(
        "/trainee/join-requests",
        headers=_auth(t["token"]),
        json={"inviteCode": "TACT-ALI"},
    )
    jr_id = create.json()["id"]

    cancel = client.post(
        f"/trainee/join-requests/{jr_id}/cancel",
        headers=_auth(t["token"]),
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    listed = client.get(
        "/trainer/join-requests?status=pending",
        headers=_auth(actors["ali"]["token"]),
    )
    assert not any(r["id"] == jr_id for r in listed.json())

    again = client.post(
        "/trainee/join-requests",
        headers=_auth(t["token"]),
        json={"inviteCode": "TACT-ALI"},
    )
    assert again.status_code == 201


def test_already_linked_and_pending_conflicts(client: TestClient, actors: dict) -> None:
    t = _signup_trainee(client)
    create = client.post(
        "/trainee/join-requests",
        headers=_auth(t["token"]),
        json={"inviteCode": "TACT-MAYA"},
    )
    assert create.status_code == 201
    jr_id = create.json()["id"]

    dup = client.post(
        "/trainee/join-requests",
        headers=_auth(t["token"]),
        json={"inviteCode": "TACT-ALI"},
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "PENDING_EXISTS"

    accept = client.post(
        f"/trainer/join-requests/{jr_id}/accept",
        headers=_auth(actors["maya"]["token"]),
    )
    assert accept.status_code == 200

    again = client.post(
        "/trainee/link",
        headers=_auth(t["token"]),
        json={"inviteCode": "TACT-ALI"},
    )
    assert again.status_code == 409
    assert again.json()["code"] == "ALREADY_LINKED"
    assert "Leave them first" in again.json()["detail"]


def test_bad_code_and_wrong_trainer(client: TestClient, actors: dict) -> None:
    t = _signup_trainee(client)
    bad = client.post(
        "/trainee/join-requests",
        headers=_auth(t["token"]),
        json={"inviteCode": "TACT-NOPE"},
    )
    assert bad.status_code == 404
    assert bad.json()["code"] == "INVITE_NOT_FOUND"

    create = client.post(
        "/trainee/join-requests",
        headers=_auth(t["token"]),
        json={"inviteCode": "TACT-OMAR"},
    )
    jr_id = create.json()["id"]

    forbidden = client.post(
        f"/trainer/join-requests/{jr_id}/accept",
        headers=_auth(actors["ali"]["token"]),
    )
    assert forbidden.status_code == 403


def test_unlink_after_accept_chat_survives(client: TestClient, actors: dict) -> None:
    t = _signup_trainee(client)
    create = client.post(
        "/trainee/join-requests",
        headers=_auth(t["token"]),
        json={"inviteCode": "TACT-OMAR"},
    )
    jr_id = create.json()["id"]
    assert (
        client.post(
            f"/trainer/join-requests/{jr_id}/accept",
            headers=_auth(actors["omar"]["token"]),
        ).status_code
        == 200
    )

    # Open / ensure a chat thread exists (human chat with coach)
    threads_before = client.get("/chat/threads", headers=_auth(t["token"]))
    assert threads_before.status_code == 200

    unlink = client.post("/trainee/unlink", headers=_auth(t["token"]))
    assert unlink.status_code == 200, unlink.text

    roster = client.get("/trainer/trainees", headers=_auth(actors["omar"]["token"]))
    assert t["trainee_id"] not in _roster_ids(roster.json())
    assert client.get("/trainee/trainer", headers=_auth(t["token"])).json() is None

    threads_after = client.get("/chat/threads", headers=_auth(t["token"]))
    assert threads_after.status_code == 200

    # Can request again
    again = client.post(
        "/trainee/join-requests",
        headers=_auth(t["token"]),
        json={"inviteCode": "TACT-OMAR"},
    )
    assert again.status_code == 201


def test_signup_invite_creates_pending_not_link(client: TestClient, actors: dict) -> None:
    t = _signup_trainee(client, invite_code="TACT-OMAR")
    assert client.get("/trainee/trainer", headers=_auth(t["token"])).json() is None

    mine = client.get("/trainee/join-requests/mine", headers=_auth(t["token"]))
    assert mine.status_code == 200
    pending = mine.json()["pendingRequest"]
    assert pending is not None
    assert pending["status"] == "pending"
    assert pending["inviteCode"] == "TACT-OMAR"

    db = SessionLocal()
    try:
        row = db.get(models.TraineeProfile, t["trainee_id"])
        assert row is not None
        assert row.trainer_id is None
        jr = db.scalars(
            select(models.JoinRequest).where(
                models.JoinRequest.trainee_user_id == t["user_id"],
                models.JoinRequest.status == "pending",
            )
        ).first()
        assert jr is not None
    finally:
        db.close()


def test_non_pending_accept_reject_cancel(client: TestClient, actors: dict) -> None:
    t = _signup_trainee(client)
    create = client.post(
        "/trainee/join-requests",
        headers=_auth(t["token"]),
        json={"inviteCode": "TACT-OMAR"},
    )
    jr_id = create.json()["id"]
    client.post(
        f"/trainer/join-requests/{jr_id}/reject",
        headers=_auth(actors["omar"]["token"]),
    )

    again_accept = client.post(
        f"/trainer/join-requests/{jr_id}/accept",
        headers=_auth(actors["omar"]["token"]),
    )
    assert again_accept.status_code == 400

    again_cancel = client.post(
        f"/trainee/join-requests/{jr_id}/cancel",
        headers=_auth(t["token"]),
    )
    assert again_cancel.status_code == 400
