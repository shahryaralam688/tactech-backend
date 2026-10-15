"""Phase 9 — free marketplace follow / hire → same roster link as invite."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import models
from app.db.session import SessionLocal
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
        "trainer_id": (body.get("trainer") or {}).get("id"),
        "trainee_id": (body.get("trainee") or {}).get("id"),
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _reset_trainee_link(user_id: str) -> None:
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        for row in db.scalars(
            select(models.CoachFollow).where(models.CoachFollow.trainee_user_id == user_id)
        ).all():
            db.delete(row)
        now = datetime.now(timezone.utc)
        for row in db.scalars(
            select(models.JoinRequest).where(
                models.JoinRequest.trainee_user_id == user_id,
                models.JoinRequest.status == "pending",
            )
        ).all():
            row.status = "cancelled"
            row.resolved_at = now
            row.updated_at = now
            db.add(row)
        for row in db.scalars(
            select(models.TrainerTraineeLink).where(
                models.TrainerTraineeLink.trainee_user_id == user_id,
                models.TrainerTraineeLink.status == "active",
            )
        ).all():
            row.status = "ended"
            row.ended_at = now
            row.ended_by_user_id = user_id
            db.add(row)
        trainee = db.scalars(
            select(models.TraineeProfile).where(models.TraineeProfile.user_id == user_id)
        ).first()
        if trainee is not None:
            trainee.trainer_id = None
            db.add(trainee)
        db.commit()
    finally:
        db.close()


def _ensure_follow_tester(password: str = "FollowTest1!") -> dict:
    """Dedicated trainee so seed roster links don't interfere."""
    from datetime import datetime, timezone

    db = SessionLocal()
    email = "follow.qa@tactech.app"
    try:
        user = db.scalars(select(models.User).where(models.User.email == email)).first()
        if user is None:
            uid = f"user-follow-{uuid4().hex[:8]}"
            tid = f"trainee-follow-{uuid4().hex[:8]}"
            user = models.User(
                id=uid,
                name="Follow QA",
                email=email,
                password_hash=hash_password(password),
                role="trainee",
                created_at=datetime.now(timezone.utc),
                assessment_completed=True,
                onboarding_completed=True,
            )
            db.add(user)
            db.add(
                models.TraineeProfile(
                    id=tid,
                    user_id=uid,
                    trainer_id=None,
                    goal="Follow tests",
                    height_cm=170,
                    weight_kg=70.0,
                    daily_calorie_target=2000,
                )
            )
            db.commit()
        else:
            user.password_hash = hash_password(password)
            trainee = db.scalars(
                select(models.TraineeProfile).where(models.TraineeProfile.user_id == user.id)
            ).first()
            if trainee is None:
                db.add(
                    models.TraineeProfile(
                        id=f"trainee-follow-{uuid4().hex[:8]}",
                        user_id=user.id,
                        trainer_id=None,
                        goal="Follow tests",
                        height_cm=170,
                        weight_kg=70.0,
                        daily_calorie_target=2000,
                    )
                )
            else:
                trainee.trainer_id = None
                db.add(trainee)
            for row in db.scalars(
                select(models.CoachFollow).where(models.CoachFollow.trainee_user_id == user.id)
            ).all():
                db.delete(row)
            db.commit()
    finally:
        db.close()
    return {"email": email, "password": password}


@pytest.fixture(scope="module")
def actors(client: TestClient) -> dict:
    settings = get_settings()
    tester = _ensure_follow_tester()
    return {
        "sara": _login(client, "sara.coach@tactech.app", settings.seed_trainer_password),
        "omar": _login(client, "omar.coach@tactech.app", settings.seed_trainer_password),
        "maya": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
        "trainee": _login(client, tester["email"], tester["password"]),
        "seed_trainee": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
    }


def test_non_trainee_cannot_follow(client: TestClient, actors: dict) -> None:
    res = client.post(
        "/coaches/cp-sara/follow",
        headers=_auth(actors["sara"]["token"]),
        json={},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


def test_follow_pending_accept_roster(client: TestClient, actors: dict) -> None:
    _reset_trainee_link(actors["trainee"]["user_id"])
    # Ensure Sara is manual
    client.patch(
        "/me/coach-profile",
        headers=_auth(actors["sara"]["token"]),
        json={"followMode": "manual"},
    )

    create = client.post(
        "/coaches/cp-sara/follow",
        headers=_auth(actors["trainee"]["token"]),
        json={"note": "Can we start this month?"},
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["status"] == "pending"
    assert body["coachProfileId"] == "cp-sara"
    follow_id = body["id"]
    assert body["threadId"]

    state = client.get(
        "/coaches/cp-sara/follow",
        headers=_auth(actors["trainee"]["token"]),
    )
    assert state.status_code == 200
    assert state.json()["status"] == "pending"

    detail = client.get(
        "/coaches/cp-sara",
        headers=_auth(actors["trainee"]["token"]),
    )
    assert detail.status_code == 200
    assert detail.json()["followStatus"] == "pending"

    # Not on roster yet
    roster_before = client.get(
        "/trainer/trainees",
        headers=_auth(actors["sara"]["token"]),
    )
    assert roster_before.status_code == 200
    assert actors["trainee"]["trainee_id"] not in {t["id"] for t in roster_before.json()}

    pending = client.get(
        "/me/coach-follows?status=pending",
        headers=_auth(actors["sara"]["token"]),
    )
    assert pending.status_code == 200
    assert any(i["id"] == follow_id for i in pending.json()["items"])

    accepted = client.post(
        f"/me/coach-follows/{follow_id}/accept",
        headers=_auth(actors["sara"]["token"]),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "active"

    roster = client.get("/trainer/trainees", headers=_auth(actors["sara"]["token"]))
    assert roster.status_code == 200
    assert actors["trainee"]["trainee_id"] in {t["id"] for t in roster.json()}

    my_trainer = client.get("/trainee/trainer", headers=_auth(actors["trainee"]["token"]))
    assert my_trainer.status_code == 200
    assert my_trainer.json() is not None
    assert my_trainer.json()["trainer"]["id"] == actors["sara"]["trainer_id"]


def test_auto_accept_links_immediately(client: TestClient, actors: dict) -> None:
    _reset_trainee_link(actors["trainee"]["user_id"])
    client.patch(
        "/me/coach-profile",
        headers=_auth(actors["omar"]["token"]),
        json={"followMode": "auto_accept"},
    )
    create = client.post(
        "/coaches/cp-omar/follow",
        headers=_auth(actors["trainee"]["token"]),
        json={},
    )
    assert create.status_code == 200, create.text
    assert create.json()["status"] == "active"

    roster = client.get("/trainer/trainees", headers=_auth(actors["omar"]["token"]))
    assert actors["trainee"]["trainee_id"] in {t["id"] for t in roster.json()}

    my_trainer = client.get("/trainee/trainer", headers=_auth(actors["trainee"]["token"]))
    assert my_trainer.json()["trainer"]["id"] == actors["omar"]["trainer_id"]


def test_second_coach_while_active_409(client: TestClient, actors: dict) -> None:
    _reset_trainee_link(actors["trainee"]["user_id"])
    client.patch(
        "/me/coach-profile",
        headers=_auth(actors["omar"]["token"]),
        json={"followMode": "auto_accept"},
    )
    first = client.post(
        "/coaches/cp-omar/follow",
        headers=_auth(actors["trainee"]["token"]),
        json={},
    )
    assert first.status_code == 200
    second = client.post(
        "/coaches/cp-sara/follow",
        headers=_auth(actors["trainee"]["token"]),
        json={},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "CONFLICT"


def test_already_linked_via_invite_same_coach(client: TestClient, actors: dict) -> None:
    _reset_trainee_link(actors["trainee"]["user_id"])
    pending = client.post(
        "/trainee/join-requests",
        headers=_auth(actors["trainee"]["token"]),
        json={"inviteCode": "TACT-SARA"},
    )
    assert pending.status_code == 201, pending.text
    accept = client.post(
        f"/trainer/join-requests/{pending.json()['id']}/accept",
        headers=_auth(actors["sara"]["token"]),
    )
    assert accept.status_code == 200, accept.text

    again = client.post(
        "/coaches/cp-sara/follow",
        headers=_auth(actors["trainee"]["token"]),
        json={},
    )
    assert again.status_code == 409
    assert again.json()["code"] == "ALREADY_LINKED"


def test_decline_not_on_roster(client: TestClient, actors: dict) -> None:
    _reset_trainee_link(actors["trainee"]["user_id"])
    client.patch(
        "/me/coach-profile",
        headers=_auth(actors["sara"]["token"]),
        json={"followMode": "manual"},
    )
    create = client.post(
        "/coaches/cp-sara/follow",
        headers=_auth(actors["trainee"]["token"]),
        json={},
    )
    assert create.status_code == 201
    follow_id = create.json()["id"]

    declined = client.post(
        f"/me/coach-follows/{follow_id}/decline",
        headers=_auth(actors["sara"]["token"]),
    )
    assert declined.status_code == 200
    assert declined.json()["status"] == "declined"

    roster = client.get("/trainer/trainees", headers=_auth(actors["sara"]["token"]))
    assert actors["trainee"]["trainee_id"] not in {t["id"] for t in roster.json()}


def test_end_either_side_keeps_chat(client: TestClient, actors: dict) -> None:
    _reset_trainee_link(actors["trainee"]["user_id"])
    client.patch(
        "/me/coach-profile",
        headers=_auth(actors["omar"]["token"]),
        json={"followMode": "auto_accept"},
    )
    create = client.post(
        "/coaches/cp-omar/follow",
        headers=_auth(actors["trainee"]["token"]),
        json={"note": "hello"},
    )
    assert create.status_code == 200
    thread_id = create.json()["threadId"]
    follow_id = create.json()["id"]

    msgs = client.get(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(actors["trainee"]["token"]),
    )
    assert msgs.status_code == 200, msgs.text

    ended = client.post(
        "/me/coach-follow/end",
        headers=_auth(actors["trainee"]["token"]),
    )
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"

    roster = client.get("/trainer/trainees", headers=_auth(actors["omar"]["token"]))
    assert actors["trainee"]["trainee_id"] not in {t["id"] for t in roster.json()}

    # Chat still readable
    msgs2 = client.get(
        f"/chat/threads/{thread_id}/messages",
        headers=_auth(actors["trainee"]["token"]),
    )
    assert msgs2.status_code == 200

    # Re-follow and end from trainer
    _reset_trainee_link(actors["trainee"]["user_id"])
    create2 = client.post(
        "/coaches/cp-omar/follow",
        headers=_auth(actors["trainee"]["token"]),
        json={},
    )
    assert create2.status_code == 200
    follow_id = create2.json()["id"]
    end_t = client.post(
        f"/me/coach-follows/{follow_id}/end",
        headers=_auth(actors["omar"]["token"]),
    )
    assert end_t.status_code == 200
    assert end_t.json()["status"] == "ended"


def test_contact_and_inquire_without_follow(client: TestClient, actors: dict) -> None:
    _reset_trainee_link(actors["trainee"]["user_id"])
    contact = client.post(
        "/coaches/cp-ali/contact",
        headers=_auth(actors["trainee"]["token"]),
        json={"message": "Just saying hi"},
    )
    assert contact.status_code == 200, contact.text
    assert contact.json()["threadId"]

    pkgs = client.get(
        "/coaches/cp-maya/packages",
        headers=_auth(actors["trainee"]["token"]),
    )
    assert pkgs.status_code == 200
    items = pkgs.json()["items"]
    if items:
        inquire = client.post(
            f"/coaches/cp-maya/packages/{items[0]['id']}/inquire",
            headers=_auth(actors["trainee"]["token"]),
            json={},
        )
        assert inquire.status_code == 200, inquire.text


def test_idempotent_double_follow(client: TestClient, actors: dict) -> None:
    _reset_trainee_link(actors["trainee"]["user_id"])
    client.patch(
        "/me/coach-profile",
        headers=_auth(actors["sara"]["token"]),
        json={"followMode": "manual"},
    )
    a = client.post(
        "/coaches/cp-sara/follow",
        headers=_auth(actors["trainee"]["token"]),
        json={},
    )
    assert a.status_code == 201
    b = client.post(
        "/coaches/cp-sara/follow",
        headers=_auth(actors["trainee"]["token"]),
        json={},
    )
    assert b.status_code == 200
    assert b.json()["id"] == a.json()["id"]
    assert b.json()["status"] == "pending"
