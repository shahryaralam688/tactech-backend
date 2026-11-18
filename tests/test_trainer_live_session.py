"""GET /trainer/trainees/{id}/sessions/active - trainer live view of a trainee's workout.

Uses its own throwaway trainee + sessions (removed afterwards); tokens are signed
directly so no login rate-limit / Redis flush is needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.security import create_token
from app.db import models
from app.db.session import SessionLocal
from app.main import app
from app.services.trainer_service import LIVE_SESSION_MAX_IDLE

MAYA_USER, MAYA_TRAINER = "user-trainer-maya", "trainer-maya"
ALI_USER, ALI_TRAINER = "user-trainer-ali", "trainer-ali"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _trainer_headers(user_id: str, trainer_id: str) -> dict[str, str]:
    token, _, _ = create_token(
        settings=get_settings(),
        user_id=user_id,
        role="trainer",
        trainer_id=trainer_id,
        trainee_id=None,
        token_type="access",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def world():
    """A throwaway trainee on Maya's roster plus a plan and exercise to hang sessions on."""
    tag = uuid4().hex[:8]
    user_id, trainee_id = f"user-live-{tag}", f"trainee-live-{tag}"
    db = SessionLocal()
    try:
        plan = db.scalars(select(models.WorkoutPlan).where(models.WorkoutPlan.deleted_at.is_(None))).first()
        exercise = db.scalars(select(models.Exercise)).first()
        assert plan and exercise, "seed data (plan + exercise) required"
        db.add(
            models.User(
                id=user_id,
                name="Live Test",
                email=f"live-{tag}@test.invalid",
                password_hash="x",
                role="trainee",
                created_at=_now(),
            )
        )
        db.flush()
        db.add(
            models.TraineeProfile(
                id=trainee_id,
                user_id=user_id,
                trainer_id=MAYA_TRAINER,
                goal="test",
                height_cm=170,
                weight_kg=70.0,
                daily_calorie_target=2000,
            )
        )
        db.commit()
        ctx = {"trainee_id": trainee_id, "plan_id": plan.id, "exercise_id": exercise.id}
    finally:
        db.close()
    yield ctx
    db = SessionLocal()
    try:
        db.execute(delete(models.WorkoutSession).where(models.WorkoutSession.trainee_id == trainee_id))
        db.execute(delete(models.TraineeProfile).where(models.TraineeProfile.id == trainee_id))
        db.execute(delete(models.User).where(models.User.id == user_id))
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean_sessions(world):
    def wipe() -> None:
        db = SessionLocal()
        try:
            db.execute(delete(models.WorkoutSession).where(models.WorkoutSession.trainee_id == world["trainee_id"]))
            db.commit()
        finally:
            db.close()

    wipe()
    yield
    wipe()


def _make_session(
    world: dict,
    *,
    status: str = "active",
    started_ago: timedelta = timedelta(minutes=10),
    set_ago: timedelta | None = None,
) -> str:
    sid = str(uuid4())
    db = SessionLocal()
    try:
        db.add(
            models.WorkoutSession(
                id=sid,
                trainee_id=world["trainee_id"],
                plan_id=world["plan_id"],
                status=status,
                started_at=_now() - started_ago,
                completed_at=None if status == "active" else _now(),
            )
        )
        db.flush()
        if set_ago is not None:
            db.add(
                models.WorkoutSessionSet(
                    id=f"{sid}_{world['exercise_id']}_1",
                    session_id=sid,
                    exercise_id=world["exercise_id"],
                    set_number=1,
                    reps=8,
                    weight_kg=60.0,
                    finished_at=_now() - set_ago,
                )
            )
        db.commit()
    finally:
        db.close()
    return sid


def _get(client: TestClient, trainee_id: str, headers: dict[str, str]):
    return client.get(f"/trainer/trainees/{trainee_id}/sessions/active", headers=headers)


def test_owner_trainer_reads_active_session(client: TestClient, world: dict) -> None:
    sid = _make_session(world, set_ago=timedelta(minutes=2))
    res = _get(client, world["trainee_id"], _trainer_headers(MAYA_USER, MAYA_TRAINER))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == sid
    assert body["traineeId"] == world["trainee_id"]
    assert body["status"] == "active"
    assert body["completedAt"] is None
    assert [s["setNumber"] for s in body["sets"]] == [1]
    assert body["sets"][0]["exerciseId"] == world["exercise_id"]
    assert set(body) == {
        "id", "traineeId", "planId", "planDayId", "status",
        "startedAt", "completedAt", "workoutLogId", "sets",
    }


def test_other_trainer_is_forbidden(client: TestClient, world: dict) -> None:
    _make_session(world)
    res = _get(client, world["trainee_id"], _trainer_headers(ALI_USER, ALI_TRAINER))
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


def test_unknown_trainee_is_404(client: TestClient) -> None:
    res = _get(client, "trainee-does-not-exist", _trainer_headers(MAYA_USER, MAYA_TRAINER))
    assert res.status_code == 404


def test_no_session_returns_null(client: TestClient, world: dict) -> None:
    res = _get(client, world["trainee_id"], _trainer_headers(MAYA_USER, MAYA_TRAINER))
    assert res.status_code == 200
    assert res.json() is None


@pytest.mark.parametrize("status", ["completed", "discarded"])
def test_finished_sessions_never_returned(client: TestClient, world: dict, status: str) -> None:
    _make_session(world, status=status)
    res = _get(client, world["trainee_id"], _trainer_headers(MAYA_USER, MAYA_TRAINER))
    assert res.status_code == 200
    assert res.json() is None


def test_stale_session_without_sets_hidden(client: TestClient, world: dict) -> None:
    _make_session(world, started_ago=LIVE_SESSION_MAX_IDLE + timedelta(minutes=5))
    res = _get(client, world["trainee_id"], _trainer_headers(MAYA_USER, MAYA_TRAINER))
    assert res.status_code == 200
    assert res.json() is None


def test_stale_by_last_set_hidden(client: TestClient, world: dict) -> None:
    _make_session(
        world,
        started_ago=LIVE_SESSION_MAX_IDLE + timedelta(hours=1),
        set_ago=LIVE_SESSION_MAX_IDLE + timedelta(minutes=5),
    )
    res = _get(client, world["trainee_id"], _trainer_headers(MAYA_USER, MAYA_TRAINER))
    assert res.json() is None


def test_old_session_with_recent_set_still_live(client: TestClient, world: dict) -> None:
    """Staleness is measured from last activity, not from the start."""
    sid = _make_session(
        world,
        started_ago=LIVE_SESSION_MAX_IDLE + timedelta(hours=1),
        set_ago=timedelta(minutes=1),
    )
    res = _get(client, world["trainee_id"], _trainer_headers(MAYA_USER, MAYA_TRAINER))
    assert res.status_code == 200
    assert res.json()["id"] == sid


def test_duplicate_active_rows_return_newest(client: TestClient, world: dict) -> None:
    _make_session(world, started_ago=timedelta(minutes=30))
    newest = _make_session(world, started_ago=timedelta(minutes=5))
    res = _get(client, world["trainee_id"], _trainer_headers(MAYA_USER, MAYA_TRAINER))
    assert res.status_code == 200
    assert res.json()["id"] == newest


def test_trainee_token_cannot_use_trainer_endpoint(client: TestClient, world: dict) -> None:
    token, _, _ = create_token(
        settings=get_settings(),
        user_id="user-jordan",
        role="trainee",
        trainer_id=None,
        trainee_id="trainee-jordan",
        token_type="access",
    )
    res = _get(client, world["trainee_id"], {"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_access_is_lost_when_trainee_changes_trainer(client: TestClient, world: dict) -> None:
    _make_session(world)
    db = SessionLocal()
    try:
        db.get(models.TraineeProfile, world["trainee_id"]).trainer_id = ALI_TRAINER
        db.commit()
    finally:
        db.close()
    try:
        assert _get(client, world["trainee_id"], _trainer_headers(MAYA_USER, MAYA_TRAINER)).status_code == 403
        assert _get(client, world["trainee_id"], _trainer_headers(ALI_USER, ALI_TRAINER)).status_code == 200
    finally:
        db = SessionLocal()
        try:
            db.get(models.TraineeProfile, world["trainee_id"]).trainer_id = MAYA_TRAINER
            db.commit()
        finally:
            db.close()
