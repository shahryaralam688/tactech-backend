"""PART E — AI plan source lock (trainee edit/delete only for source=ai)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    return {
        "token": body["accessToken"],
        "user_id": body["user"]["id"],
        "trainee_id": (body.get("trainee") or {}).get("id"),
        "trainer_id": (body.get("trainer") or {}).get("id"),
    }


@pytest.fixture(scope="module")
def users(client: TestClient) -> dict:
    s = get_settings()
    return {
        "trainee": _login(client, "trainee@tactech.app", s.seed_trainee_password),
        "trainer": _login(client, "trainer@tactech.app", s.seed_trainer_password),
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_plan(*, source: str, trainer_id: str | None, owner_trainee_id: str | None) -> str:
    from datetime import datetime, timezone

    from sqlalchemy import delete

    plan_id = f"plan-src-{uuid4().hex[:10]}"
    db = SessionLocal()
    try:
        plan = models.WorkoutPlan(
            id=plan_id,
            trainer_id=trainer_id,
            source=source,
            owner_trainee_id=owner_trainee_id,
            title="Lock Test Plan",
            focus="Test",
            duration_minutes=45,
            level="Beginner",
            days_per_week=3,
            notes=None,
        )
        db.add(plan)
        if owner_trainee_id:
            db.execute(
                delete(models.PlanAssignment).where(
                    models.PlanAssignment.trainee_id == owner_trainee_id
                )
            )
            db.add(
                models.PlanAssignment(
                    id=str(uuid4()),
                    plan_id=plan_id,
                    trainee_id=owner_trainee_id,
                    assigned_at=datetime.now(timezone.utc),
                )
            )
        db.commit()
    finally:
        db.close()
    return plan_id


def test_assigned_plan_includes_source(client: TestClient, users: dict) -> None:
    trainee = users["trainee"]
    plan_id = _make_plan(
        source="ai",
        trainer_id=None,
        owner_trainee_id=trainee["trainee_id"],
    )
    res = client.get("/trainee/assigned-plan", headers=_auth(trainee["token"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body is not None
    assert body["id"] == plan_id
    assert body["source"] == "ai"


def test_trainee_patch_trainer_plan_403(client: TestClient, users: dict) -> None:
    trainee = users["trainee"]
    trainer = users["trainer"]
    plan_id = _make_plan(
        source="trainer",
        trainer_id=trainer["trainer_id"],
        owner_trainee_id=trainee["trainee_id"],
    )
    res = client.patch(
        f"/trainee/ai-plans/{plan_id}",
        headers=_auth(trainee["token"]),
        json={"title": "Hacked"},
    )
    assert res.status_code == 403, res.text
    assert res.json()["code"] == "PLAN_LOCKED"


def test_trainee_delete_ai_plan_204(client: TestClient, users: dict) -> None:
    trainee = users["trainee"]
    plan_id = _make_plan(
        source="ai",
        trainer_id=None,
        owner_trainee_id=trainee["trainee_id"],
    )
    res = client.delete(f"/trainee/ai-plans/{plan_id}", headers=_auth(trainee["token"]))
    assert res.status_code == 204, res.text
    assigned = client.get("/trainee/assigned-plan", headers=_auth(trainee["token"]))
    assert assigned.status_code == 200
    assert assigned.json() is None


def test_trainee_patch_ai_plan_200(client: TestClient, users: dict) -> None:
    trainee = users["trainee"]
    plan_id = _make_plan(
        source="ai",
        trainer_id=None,
        owner_trainee_id=trainee["trainee_id"],
    )
    res = client.patch(
        f"/trainee/ai-plans/{plan_id}",
        headers=_auth(trainee["token"]),
        json={"title": "My AI Week", "focus": "Strength"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "My AI Week"
    assert res.json()["source"] == "ai"


def test_trainer_patch_own_plan_still_works(client: TestClient, users: dict) -> None:
    trainer = users["trainer"]
    create = client.post(
        "/trainer/plans",
        headers=_auth(trainer["token"]),
        json={
            "title": "Coach Plan",
            "focus": "Hypertrophy",
            "durationMinutes": 50,
            "level": "Intermediate",
            "daysPerWeek": 4,
            "days": [
                {
                    "weekday": "monday",
                    "title": "A",
                    "focus": "Push",
                    "durationMinutes": 50,
                    "exercises": [
                        {
                            "exerciseId": "ex-squat",
                            "sets": 3,
                            "reps": 8,
                            "restSeconds": 90,
                        }
                    ],
                }
            ],
            "exercises": [],
        },
    )
    assert create.status_code == 201, create.text
    plan = create.json()
    assert plan["source"] == "trainer"
    patch = client.patch(
        f"/trainer/plans/{plan['id']}",
        headers=_auth(trainer["token"]),
        json={"title": "Coach Plan v2"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["title"] == "Coach Plan v2"
    assert patch.json()["source"] == "trainer"
