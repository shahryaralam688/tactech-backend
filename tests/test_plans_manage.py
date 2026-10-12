"""Plan PATCH/DELETE + assign/unassign contract tests for iOS Trainer app."""

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
        "trainer_id": (body.get("trainer") or {}).get("id"),
        "trainee_id": (body.get("trainee") or {}).get("id"),
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def actors(client: TestClient) -> dict:
    settings = get_settings()
    db = SessionLocal()
    kashif = db.scalars(select(models.User).where(models.User.email == "kashifabc@gmail.com")).first()
    if kashif is not None:
        kashif.password_hash = hash_password("123456")
        db.commit()
    # Ensure trainone linked to Kashif
    trainone = db.scalars(select(models.User).where(models.User.email == "trainone@gmail.com")).first()
    if trainone is not None and kashif is not None:
        tp = db.scalars(select(models.TrainerProfile).where(models.TrainerProfile.user_id == kashif.id)).first()
        tr = db.scalars(select(models.TraineeProfile).where(models.TraineeProfile.user_id == trainone.id)).first()
        if tp and tr:
            tr.trainer_id = tp.id
            db.commit()
    db.close()

    trainer = _login(client, "kashifabc@gmail.com", "123456")
    trainee = _login(client, "trainone@gmail.com", "123456")
    other = _login(client, "trainer@tactech.app", settings.seed_trainer_password)
    return {"trainer": trainer, "trainee": trainee, "other": other}


def _minimal_plan_body(title: str = "Contract plan") -> dict:
    return {
        "title": title,
        "focus": "Strength",
        "durationMinutes": 45,
        "level": "Intermediate",
        "daysPerWeek": 3,
        "notes": "test",
        "exercises": [
            {"exerciseId": "ex-squat", "sets": 3, "reps": 8, "restSeconds": 90}
        ],
        "days": [
            {
                "weekday": "monday",
                "title": "Lower",
                "focus": "Squat",
                "durationMinutes": 45,
                "exercises": [
                    {"exerciseId": "ex-squat", "sets": 3, "reps": 8, "restSeconds": 90}
                ],
            }
        ],
    }


def test_patch_plan_updates_list_and_assigned(client: TestClient, actors: dict) -> None:
    trainer = actors["trainer"]
    trainee = actors["trainee"]
    create = client.post(
        "/trainer/plans",
        headers=_auth(trainer["token"]),
        json=_minimal_plan_body("Original title"),
    )
    assert create.status_code == 201, create.text
    plan_id = create.json()["id"]

    patch = client.patch(
        f"/trainer/plans/{plan_id}",
        headers=_auth(trainer["token"]),
        json=_minimal_plan_body("Patched title"),
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["title"] == "Patched title"
    assert patch.json()["id"] == plan_id
    assert patch.json()["trainerId"] == trainer["trainer_id"]

    listed = client.get("/trainer/plans", headers=_auth(trainer["token"]))
    assert any(p["id"] == plan_id and p["title"] == "Patched title" for p in listed.json())

    assign = client.post(
        "/trainer/assignments",
        headers=_auth(trainer["token"]),
        json={"planId": plan_id, "traineeId": trainee["trainee_id"]},
    )
    assert assign.status_code == 201, assign.text

    assigned = client.get("/trainee/assigned-plan", headers=_auth(trainee["token"]))
    assert assigned.status_code == 200
    assert assigned.json()["id"] == plan_id
    assert assigned.json()["title"] == "Patched title"

    again = client.patch(
        f"/trainer/plans/{plan_id}",
        headers=_auth(trainer["token"]),
        json=_minimal_plan_body("Live update"),
    )
    assert again.status_code == 200
    assigned2 = client.get("/trainee/assigned-plan", headers=_auth(trainee["token"]))
    assert assigned2.json()["title"] == "Live update"


def test_unassign_by_query_idempotent(client: TestClient, actors: dict) -> None:
    trainer = actors["trainer"]
    trainee = actors["trainee"]
    create = client.post(
        "/trainer/plans",
        headers=_auth(trainer["token"]),
        json=_minimal_plan_body(f"Unassign {uuid4().hex[:6]}"),
    )
    plan_id = create.json()["id"]
    assign = client.post(
        "/trainer/assignments",
        headers=_auth(trainer["token"]),
        json={"planId": plan_id, "traineeId": trainee["trainee_id"]},
    )
    assert assign.status_code == 201, assign.text
    assert client.get("/trainee/assigned-plan", headers=_auth(trainee["token"])).json()["id"] == plan_id

    first = client.delete(
        f"/trainer/assignments?planId={plan_id}&traineeId={trainee['trainee_id']}",
        headers=_auth(trainer["token"]),
    )
    assert first.status_code == 204
    assert client.get("/trainee/assigned-plan", headers=_auth(trainee["token"])).json() is None

    second = client.delete(
        f"/trainer/assignments?planId={plan_id}&traineeId={trainee['trainee_id']}",
        headers=_auth(trainer["token"]),
    )
    assert second.status_code == 204


def test_delete_plan_soft_clears_assignment_keeps_logs(client: TestClient, actors: dict) -> None:
    trainer = actors["trainer"]
    trainee = actors["trainee"]
    create = client.post(
        "/trainer/plans",
        headers=_auth(trainer["token"]),
        json=_minimal_plan_body(f"Delete me {uuid4().hex[:6]}"),
    )
    plan_id = create.json()["id"]
    assert (
        client.post(
            "/trainer/assignments",
            headers=_auth(trainer["token"]),
            json={"planId": plan_id, "traineeId": trainee["trainee_id"]},
        ).status_code
        == 201
    )

    log = client.post(
        "/trainee/logs",
        headers=_auth(trainee["token"]),
        json={
            "planId": plan_id,
            "durationMinutes": 40,
            "sets": [{"exerciseId": "ex-squat", "setNumber": 1, "reps": 8, "weightKg": 60}],
        },
    )
    assert log.status_code == 201, log.text
    log_id = log.json()["id"]

    deleted = client.delete(f"/trainer/plans/{plan_id}", headers=_auth(trainer["token"]))
    assert deleted.status_code == 204

    listed = client.get("/trainer/plans", headers=_auth(trainer["token"]))
    assert all(p["id"] != plan_id for p in listed.json())
    assert client.get("/trainee/assigned-plan", headers=_auth(trainee["token"])).json() is None

    logs = client.get("/trainee/logs", headers=_auth(trainee["token"]))
    assert logs.status_code == 200
    assert any(row["id"] == log_id for row in logs.json())


def test_other_trainer_cannot_mutate(client: TestClient, actors: dict) -> None:
    trainer = actors["trainer"]
    other = actors["other"]
    trainee = actors["trainee"]
    create = client.post(
        "/trainer/plans",
        headers=_auth(trainer["token"]),
        json=_minimal_plan_body(f"Private {uuid4().hex[:6]}"),
    )
    plan_id = create.json()["id"]

    patch = client.patch(
        f"/trainer/plans/{plan_id}",
        headers=_auth(other["token"]),
        json=_minimal_plan_body("Hijack"),
    )
    assert patch.status_code in {403, 404}

    delete = client.delete(f"/trainer/plans/{plan_id}", headers=_auth(other["token"]))
    assert delete.status_code in {403, 404}

    unassign = client.delete(
        f"/trainer/assignments?planId={plan_id}&traineeId={trainee['trainee_id']}",
        headers=_auth(other["token"]),
    )
    assert unassign.status_code in {403, 404}
