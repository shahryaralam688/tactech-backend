"""Trainer ↔ trainee invite link + unlink / remove."""

from __future__ import annotations

from datetime import datetime, timezone
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
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def actors(client: TestClient) -> dict:
    # Avoid login rate-limit between tests / prior sessions
    from app.core.redis import create_redis_client

    r = create_redis_client()
    try:
        r.flushdb()
    finally:
        r.close()
    settings = get_settings()
    return {
        "maya": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
        "ali": _login(client, "ali.coach@tactech.app", settings.seed_trainer_password),
        "jordan": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
    }


def _roster_ids(roster_json: list) -> set[str]:
    return {t["id"] for t in roster_json}


def _cancel_pending_join_requests(trainee_user_id: str) -> None:
    db = SessionLocal()
    try:
        for row in db.scalars(
            select(models.JoinRequest).where(
                models.JoinRequest.trainee_user_id == trainee_user_id,
                models.JoinRequest.status == "pending",
            )
        ).all():
            row.status = "cancelled"
            row.resolved_at = datetime.now(timezone.utc)
            row.updated_at = row.resolved_at
            db.add(row)
        db.commit()
    finally:
        db.close()


def _ensure_jordan_linked_to_maya(client: TestClient, actors: dict) -> None:
    cur = client.get("/trainee/trainer", headers=_auth(actors["jordan"]["token"]))
    assert cur.status_code == 200
    if cur.json() is not None:
        unlink = client.post("/trainee/unlink", headers=_auth(actors["jordan"]["token"]))
        assert unlink.status_code in (200, 404)
    _cancel_pending_join_requests(actors["jordan"]["user_id"])
    link = client.post(
        "/trainee/join-requests",
        headers=_auth(actors["jordan"]["token"]),
        json={"inviteCode": "TACT-MAYA"},
    )
    assert link.status_code == 201, link.text
    assert link.json()["status"] == "pending"
    jr_id = link.json()["id"]
    accept = client.post(
        f"/trainer/join-requests/{jr_id}/accept",
        headers=_auth(actors["maya"]["token"]),
    )
    assert accept.status_code == 200, accept.text
    me = client.get("/trainee/trainer", headers=_auth(actors["jordan"]["token"]))
    assert me.status_code == 200
    assert me.json() is not None
    assert me.json()["trainer"]["id"] == "trainer-maya"


def test_link_roster_and_my_trainer(client: TestClient, actors: dict) -> None:
    _ensure_jordan_linked_to_maya(client, actors)
    me = client.get("/trainee/trainer", headers=_auth(actors["jordan"]["token"]))
    assert me.status_code == 200
    assert me.json() is not None
    assert me.json()["trainer"]["id"] == "trainer-maya"

    roster = client.get("/trainer/trainees", headers=_auth(actors["maya"]["token"]))
    assert roster.status_code == 200
    assert "trainee-jordan" in _roster_ids(roster.json())


def test_trainee_unlink_clears_roster_and_plan(client: TestClient, actors: dict) -> None:
    _ensure_jordan_linked_to_maya(client, actors)

    plans = client.get("/trainer/plans", headers=_auth(actors["maya"]["token"]))
    assert plans.status_code == 200
    assert plans.json(), "trainer needs at least one plan"
    plan_id = plans.json()[0]["id"]
    assign = client.post(
        "/trainer/assignments",
        headers=_auth(actors["maya"]["token"]),
        json={"planId": plan_id, "traineeId": "trainee-jordan"},
    )
    assert assign.status_code in (200, 201), assign.text

    ap = client.get("/trainee/assigned-plan", headers=_auth(actors["jordan"]["token"]))
    assert ap.status_code == 200
    assert ap.json() is not None

    unlink = client.post("/trainee/unlink", headers=_auth(actors["jordan"]["token"]))
    assert unlink.status_code == 200, unlink.text
    body = unlink.json()
    assert body["ok"] is True
    assert body["trainerUserId"] == actors["maya"]["user_id"]
    assert body["endedAt"]

    roster = client.get("/trainer/trainees", headers=_auth(actors["maya"]["token"]))
    assert "trainee-jordan" not in _roster_ids(roster.json())

    assert client.get("/trainee/trainer", headers=_auth(actors["jordan"]["token"])).json() is None
    assert (
        client.get("/trainee/assigned-plan", headers=_auth(actors["jordan"]["token"])).json()
        is None
    )

    # Peer trainer gets durable relationship_ended inbox (Socket emit is best-effort)
    inbox = client.get("/me/notifications", headers=_auth(actors["maya"]["token"]))
    assert inbox.status_code == 200, inbox.text
    ended = [
        n
        for n in inbox.json()["items"]
        if n["type"] == "relationship_ended"
        and (n.get("data") or {}).get("reason") == "trainee_left"
    ]
    assert ended, inbox.json()["items"][:5]
    assert ended[0]["data"].get("traineeUserId") == actors["jordan"]["user_id"]

    again = client.post("/trainee/unlink", headers=_auth(actors["jordan"]["token"]))
    assert again.status_code == 404

    relink = client.post(
        "/trainee/join-requests",
        headers=_auth(actors["jordan"]["token"]),
        json={"inviteCode": "TACT-MAYA"},
    )
    assert relink.status_code == 201, relink.text
    accept = client.post(
        f"/trainer/join-requests/{relink.json()['id']}/accept",
        headers=_auth(actors["maya"]["token"]),
    )
    assert accept.status_code == 200, accept.text


def test_trainer_remove(client: TestClient, actors: dict) -> None:
    _ensure_jordan_linked_to_maya(client, actors)
    rem = client.post(
        "/trainer/trainees/trainee-jordan/remove",
        headers=_auth(actors["maya"]["token"]),
    )
    assert rem.status_code == 200, rem.text
    assert rem.json()["ok"] is True
    assert rem.json()["traineeId"] == "trainee-jordan"

    roster = client.get("/trainer/trainees", headers=_auth(actors["maya"]["token"]))
    assert "trainee-jordan" not in _roster_ids(roster.json())
    assert client.get("/trainee/trainer", headers=_auth(actors["jordan"]["token"])).json() is None

    inbox = client.get("/me/notifications", headers=_auth(actors["jordan"]["token"]))
    assert inbox.status_code == 200, inbox.text
    ended = [
        n
        for n in inbox.json()["items"]
        if n["type"] == "relationship_ended"
        and (n.get("data") or {}).get("reason") == "trainer_removed"
    ]
    assert ended, inbox.json()["items"][:5]
    assert ended[0]["data"].get("trainerUserId") == actors["maya"]["user_id"]


def test_wrong_trainer_cannot_remove(client: TestClient, actors: dict) -> None:
    _ensure_jordan_linked_to_maya(client, actors)
    forbidden = client.post(
        "/trainer/trainees/trainee-jordan/remove",
        headers=_auth(actors["ali"]["token"]),
    )
    assert forbidden.status_code == 403


def test_link_while_active_conflicts(client: TestClient, actors: dict) -> None:
    _ensure_jordan_linked_to_maya(client, actors)
    same = client.post(
        "/trainee/link",
        headers=_auth(actors["jordan"]["token"]),
        json={"inviteCode": "TACT-MAYA"},
    )
    assert same.status_code == 409
    assert same.json()["code"] == "ALREADY_LINKED"

    other = client.post(
        "/trainee/join-requests",
        headers=_auth(actors["jordan"]["token"]),
        json={"inviteCode": "TACT-ALI"},
    )
    assert other.status_code == 409
    assert other.json()["code"] == "ALREADY_LINKED"
    assert "Leave them first" in other.json()["detail"]


def test_unlink_accepts_empty_json_body(client: TestClient, actors: dict) -> None:
    _ensure_jordan_linked_to_maya(client, actors)
    res = client.post(
        "/trainee/unlink",
        headers={
            **_auth(actors["jordan"]["token"]),
            "Content-Type": "application/json",
        },
        content=b"{}",
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["endedAt"]
    assert client.get("/trainee/trainer", headers=_auth(actors["jordan"]["token"])).json() is None


def test_remove_by_user_id(client: TestClient, actors: dict) -> None:
    _ensure_jordan_linked_to_maya(client, actors)
    rem = client.post(
        f"/trainer/trainees/{actors['jordan']['user_id']}/remove",
        headers=_auth(actors["maya"]["token"]),
    )
    assert rem.status_code == 200, rem.text
    assert rem.json()["traineeId"] == "trainee-jordan"
    assert "trainee-jordan" not in _roster_ids(
        client.get("/trainer/trainees", headers=_auth(actors["maya"]["token"])).json()
    )


def test_chat_threads_survive_unlink(client: TestClient, actors: dict) -> None:
    _ensure_jordan_linked_to_maya(client, actors)
    now = datetime.now(timezone.utc)
    thread_id = f"thr-unlink-{uuid4().hex[:10]}"
    db = SessionLocal()
    try:
        existing = db.scalars(
            select(models.ChatThread).where(
                models.ChatThread.trainer_user_id == actors["maya"]["user_id"],
                models.ChatThread.trainee_user_id == actors["jordan"]["user_id"],
            )
        ).first()
        if existing is None:
            db.add(
                models.ChatThread(
                    id=thread_id,
                    trainer_user_id=actors["maya"]["user_id"],
                    trainee_user_id=actors["jordan"]["user_id"],
                    created_at=now,
                    updated_at=now,
                )
            )
            db.commit()
            keep_id = thread_id
        else:
            keep_id = existing.id
    finally:
        db.close()

    client.post("/trainee/unlink", headers=_auth(actors["jordan"]["token"]))

    db = SessionLocal()
    try:
        still = db.get(models.ChatThread, keep_id)
        assert still is not None
    finally:
        db.close()

    inbox = client.get("/chat/threads", headers=_auth(actors["jordan"]["token"]))
    assert inbox.status_code == 200, inbox.text
