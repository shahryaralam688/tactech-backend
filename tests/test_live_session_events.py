"""Tests for notify_trainer_session_changed: emit payload, isolation, error tolerance,
DB-commit ordering, and planDayId storage.

Trainee: Jordan Hale (trainee-jordan / user-jordan), trainer: Maya (trainer-maya / user-trainer-maya).
Trainee with no trainer: a throwaway profile created per module.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.security import create_token
from app.db import models
from app.db.session import SessionLocal
from app.main import app

JORDAN_USER = "user-jordan"
JORDAN_TRAINEE = "trainee-jordan"
MAYA_USER = "user-trainer-maya"
MAYA_TRAINER = "trainer-maya"

# plan-lower is assigned to Jordan in seed
PLAN_ID = "plan-lower"


# ── auth helpers ──────────────────────────────────────────────────────────────

def _trainee_headers(user_id: str, trainee_id: str) -> dict[str, str]:
    token, _, _ = create_token(
        settings=get_settings(),
        user_id=user_id,
        role="trainee",
        trainer_id=None,
        trainee_id=trainee_id,
        token_type="access",
    )
    return {"Authorization": f"Bearer {token}"}


def _jordan_headers() -> dict[str, str]:
    return _trainee_headers(JORDAN_USER, JORDAN_TRAINEE)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def no_trainer_trainee():
    """A throwaway trainee with trainer_id=None."""
    tag = uuid4().hex[:8]
    user_id = f"user-notrainer-{tag}"
    trainee_id = f"trainee-notrainer-{tag}"
    db = SessionLocal()
    try:
        db.add(models.User(
            id=user_id, name="No Trainer", email=f"nt-{tag}@test.invalid",
            password_hash="x", role="trainee", created_at=datetime.now(timezone.utc),
        ))
        db.flush()
        db.add(models.TraineeProfile(
            id=trainee_id, user_id=user_id, trainer_id=None,
            goal="test", height_cm=170, weight_kg=70, daily_calorie_target=2000,
        ))
        db.commit()
    finally:
        db.close()
    yield {"user_id": user_id, "trainee_id": trainee_id}
    db = SessionLocal()
    try:
        db.execute(delete(models.WorkoutSession).where(models.WorkoutSession.trainee_id == trainee_id))
        db.execute(delete(models.TraineeProfile).where(models.TraineeProfile.id == trainee_id))
        db.execute(delete(models.User).where(models.User.id == user_id))
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean_jordan_sessions():
    """Remove all Jordan's workout sessions before and after each test."""
    def wipe():
        db = SessionLocal()
        try:
            db.execute(delete(models.WorkoutSession).where(
                models.WorkoutSession.trainee_id == JORDAN_TRAINEE
            ))
            db.commit()
        finally:
            db.close()
    wipe()
    yield
    wipe()


# ── emit capture helper ───────────────────────────────────────────────────────

def _patch_emit():
    """Patch chat_hub.emit_workout_session_changed at the lowest level.

    Returns the patcher and a list that collects (user_id, payload) tuples.
    """
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _fake_emit(user_id: str, payload: dict[str, Any]) -> None:
        calls.append((user_id, payload))

    mock = AsyncMock(side_effect=_fake_emit)
    patcher = patch(
        "app.realtime.chat_hub.ChatHub.emit_workout_session_changed",
        new=mock,
    )
    return patcher, calls


# ── 1. Each action emits once to user:{trainerUserId} ────────────────────────

class TestEmitPayload:
    def test_start_emits_once(self, client: TestClient) -> None:
        patcher, calls = _patch_emit()
        with patcher:
            res = client.post(
                "/trainee/sessions",
                json={"planId": PLAN_ID},
                headers=_jordan_headers(),
            )
        assert res.status_code == 201, res.text
        assert len(calls) == 1
        user_id, payload = calls[0]
        assert user_id == MAYA_USER
        session_id = res.json()["id"]
        _assert_payload(payload, session_id=session_id, status="active", action="started")

    def test_set_logged_emits_once(self, client: TestClient) -> None:
        # start without patching
        start_res = client.post(
            "/trainee/sessions", json={"planId": PLAN_ID}, headers=_jordan_headers()
        )
        assert start_res.status_code == 201
        session_id = start_res.json()["id"]
        exercise_id = _first_exercise_id()

        patcher, calls = _patch_emit()
        with patcher:
            res = client.post(
                f"/trainee/sessions/{session_id}/sets",
                json={"exerciseId": exercise_id, "setNumber": 1, "reps": 10, "weightKg": 60.0},
                headers=_jordan_headers(),
            )
        assert res.status_code == 200, res.text
        assert len(calls) == 1
        user_id, payload = calls[0]
        assert user_id == MAYA_USER
        _assert_payload(payload, session_id=session_id, status="active", action="set_logged")

    def test_complete_emits_once(self, client: TestClient) -> None:
        session_id, exercise_id = _start_with_set(client)

        patcher, calls = _patch_emit()
        with patcher:
            res = client.post(
                f"/trainee/sessions/{session_id}/complete",
                headers=_jordan_headers(),
            )
        assert res.status_code == 200, res.text
        assert len(calls) == 1
        user_id, payload = calls[0]
        assert user_id == MAYA_USER
        _assert_payload(payload, session_id=session_id, status="completed", action="completed")

    def test_discard_emits_once(self, client: TestClient) -> None:
        start_res = client.post(
            "/trainee/sessions", json={"planId": PLAN_ID}, headers=_jordan_headers()
        )
        assert start_res.status_code == 201
        session_id = start_res.json()["id"]

        patcher, calls = _patch_emit()
        with patcher:
            res = client.post(
                f"/trainee/sessions/{session_id}/discard",
                headers=_jordan_headers(),
            )
        assert res.status_code == 204, res.text
        assert len(calls) == 1
        user_id, payload = calls[0]
        assert user_id == MAYA_USER
        _assert_payload(payload, session_id=session_id, status="discarded", action="discarded")

    def test_payload_has_exactly_the_required_keys(self, client: TestClient) -> None:
        patcher, calls = _patch_emit()
        with patcher:
            res = client.post(
                "/trainee/sessions",
                json={"planId": PLAN_ID},
                headers=_jordan_headers(),
            )
        assert res.status_code == 201
        _, payload = calls[0]
        assert set(payload.keys()) == {"traineeId", "sessionId", "status", "action", "occurredAt"}


# ── 2. Trainee with no trainer emits nothing ─────────────────────────────────

class TestNoTrainerEmitsNothing:
    def test_start_no_trainer_no_emit(self, client: TestClient, no_trainer_trainee: dict) -> None:
        patcher, calls = _patch_emit()
        with patcher:
            res = client.post(
                "/trainee/sessions",
                json={"planId": PLAN_ID},
                headers=_trainee_headers(
                    no_trainer_trainee["user_id"], no_trainer_trainee["trainee_id"]
                ),
            )
        # 201 or 404 (plan not assigned to this trainee's trainer) — either way no emit
        assert len(calls) == 0
        # response must not be a server error
        assert res.status_code < 500


# ── 3. Emit error does not affect trainee response ───────────────────────────

class TestEmitErrorTolerance:
    def test_start_still_201_if_emit_raises(self, client: TestClient) -> None:
        async def _boom(user_id: str, payload: dict[str, Any]) -> None:
            raise RuntimeError("socket down")

        with patch(
            "app.realtime.chat_hub.ChatHub.emit_workout_session_changed",
            new=AsyncMock(side_effect=_boom),
        ):
            res = client.post(
                "/trainee/sessions",
                json={"planId": PLAN_ID},
                headers=_jordan_headers(),
            )
        assert res.status_code == 201
        body = res.json()
        assert body["id"]
        assert body["status"] == "active"

    def test_complete_still_200_if_emit_raises(self, client: TestClient) -> None:
        session_id, _ = _start_with_set(client)

        async def _boom(user_id: str, payload: dict[str, Any]) -> None:
            raise RuntimeError("socket down")

        with patch(
            "app.realtime.chat_hub.ChatHub.emit_workout_session_changed",
            new=AsyncMock(side_effect=_boom),
        ):
            res = client.post(
                f"/trainee/sessions/{session_id}/complete",
                headers=_jordan_headers(),
            )
        assert res.status_code == 200
        body = res.json()
        assert "id" in body
        assert "durationMinutes" in body


# ── 4. FRESHNESS: DB state is visible inside the emit ────────────────────────

class TestDBFreshness:
    """Inside the emit, a new DB session must already see the committed state."""

    def test_start_db_sees_session(self, client: TestClient) -> None:
        observed: list[bool] = []

        async def _check_emit(user_id: str, payload: dict[str, Any]) -> None:
            session_id = payload["sessionId"]
            db = SessionLocal()
            try:
                row = db.get(models.WorkoutSession, session_id)
                observed.append(row is not None and row.status == "active")
            finally:
                db.close()

        with patch(
            "app.realtime.chat_hub.ChatHub.emit_workout_session_changed",
            new=AsyncMock(side_effect=_check_emit),
        ):
            res = client.post(
                "/trainee/sessions",
                json={"planId": PLAN_ID},
                headers=_jordan_headers(),
            )
        assert res.status_code == 201
        assert observed == [True], (
            "BUG: session not visible in DB inside emit — "
            "background task fired before commit"
        )

    def test_set_db_sees_new_set(self, client: TestClient) -> None:
        start_res = client.post(
            "/trainee/sessions", json={"planId": PLAN_ID}, headers=_jordan_headers()
        )
        session_id = start_res.json()["id"]
        exercise_id = _first_exercise_id()

        observed: list[int] = []  # set count inside emit

        async def _check_emit(user_id: str, payload: dict[str, Any]) -> None:
            db = SessionLocal()
            try:
                sets = db.scalars(
                    select(models.WorkoutSessionSet).where(
                        models.WorkoutSessionSet.session_id == session_id
                    )
                ).all()
                observed.append(len(sets))
            finally:
                db.close()

        with patch(
            "app.realtime.chat_hub.ChatHub.emit_workout_session_changed",
            new=AsyncMock(side_effect=_check_emit),
        ):
            client.post(
                f"/trainee/sessions/{session_id}/sets",
                json={"exerciseId": exercise_id, "setNumber": 1, "reps": 10, "weightKg": 60.0},
                headers=_jordan_headers(),
            )
        assert observed == [1], (
            "BUG: set not visible in DB inside emit — "
            f"expected 1 set, saw {observed}"
        )

    def test_complete_db_sees_completed_status(self, client: TestClient) -> None:
        session_id, _ = _start_with_set(client)
        observed: list[str] = []

        async def _check_emit(user_id: str, payload: dict[str, Any]) -> None:
            db = SessionLocal()
            try:
                row = db.get(models.WorkoutSession, session_id)
                observed.append(row.status if row else "missing")
            finally:
                db.close()

        with patch(
            "app.realtime.chat_hub.ChatHub.emit_workout_session_changed",
            new=AsyncMock(side_effect=_check_emit),
        ):
            client.post(
                f"/trainee/sessions/{session_id}/complete",
                headers=_jordan_headers(),
            )
        assert observed == ["completed"], (
            f"BUG: status inside emit was {observed!r}, expected ['completed']"
        )

    def test_discard_db_sees_discarded_status(self, client: TestClient) -> None:
        start_res = client.post(
            "/trainee/sessions", json={"planId": PLAN_ID}, headers=_jordan_headers()
        )
        session_id = start_res.json()["id"]
        observed: list[str] = []

        async def _check_emit(user_id: str, payload: dict[str, Any]) -> None:
            db = SessionLocal()
            try:
                row = db.get(models.WorkoutSession, session_id)
                observed.append(row.status if row else "missing")
            finally:
                db.close()

        with patch(
            "app.realtime.chat_hub.ChatHub.emit_workout_session_changed",
            new=AsyncMock(side_effect=_check_emit),
        ):
            client.post(
                f"/trainee/sessions/{session_id}/discard",
                headers=_jordan_headers(),
            )
        assert observed == ["discarded"], (
            f"BUG: status inside emit was {observed!r}, expected ['discarded']"
        )


# ── 5. planDayId stored correctly ────────────────────────────────────────────

class TestPlanDayIdStorage:
    def test_plan_day_id_stored_when_sent(self, client: TestClient) -> None:
        """Backend stores planDayId when iOS sends it correctly."""
        # Find a real plan_day_id to use
        day_id = _first_plan_day_id()
        res = client.post(
            "/trainee/sessions",
            json={"planId": PLAN_ID, "planDayId": day_id},
            headers=_jordan_headers(),
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["planDayId"] == day_id

        db = SessionLocal()
        try:
            row = db.get(models.WorkoutSession, body["id"])
            assert row is not None
            assert row.plan_day_id == day_id
        finally:
            db.close()

    def test_plan_day_id_null_when_not_sent(self, client: TestClient) -> None:
        res = client.post(
            "/trainee/sessions",
            json={"planId": PLAN_ID},
            headers=_jordan_headers(),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["planDayId"] is None

        db = SessionLocal()
        try:
            row = db.get(models.WorkoutSession, body["id"])
            assert row.plan_day_id is None
        finally:
            db.close()

    def test_day_id_alias_not_accepted(self, client: TestClient) -> None:
        """iOS legacy field name 'dayId' must NOT be silently stored (confirms the bug)."""
        day_id = _first_plan_day_id()
        res = client.post(
            "/trainee/sessions",
            json={"planId": PLAN_ID, "dayId": day_id},
            headers=_jordan_headers(),
        )
        assert res.status_code == 201
        # dayId is unknown — plan_day_id should be null, not the value
        body = res.json()
        assert body["planDayId"] is None, (
            "dayId was silently stored as planDayId — "
            "iOS must be fixed to send planDayId instead"
        )


# ── private helpers ───────────────────────────────────────────────────────────

def _assert_payload(
    payload: dict[str, Any],
    *,
    session_id: str,
    status: str,
    action: str,
) -> None:
    assert payload["traineeId"] == JORDAN_TRAINEE
    assert payload["sessionId"] == session_id
    assert payload["status"] == status
    assert payload["action"] == action
    assert "occurredAt" in payload
    # validate ISO-8601 Z timestamp
    assert payload["occurredAt"].endswith("Z")


def _first_exercise_id() -> str:
    db = SessionLocal()
    try:
        ex = db.scalars(select(models.Exercise)).first()
        assert ex, "No exercises in seed data"
        return ex.id
    finally:
        db.close()


def _first_plan_day_id() -> str:
    db = SessionLocal()
    try:
        day = db.scalars(select(models.PlanDay)).first()
        assert day, "No plan days in seed data"
        return day.id
    finally:
        db.close()


def _start_with_set(client: TestClient) -> tuple[str, str]:
    """Start a session and log one set; return (session_id, exercise_id)."""
    start_res = client.post(
        "/trainee/sessions", json={"planId": PLAN_ID}, headers=_jordan_headers()
    )
    assert start_res.status_code == 201
    session_id = start_res.json()["id"]
    exercise_id = _first_exercise_id()
    set_res = client.post(
        f"/trainee/sessions/{session_id}/sets",
        json={"exerciseId": exercise_id, "setNumber": 1, "reps": 10, "weightKg": 60.0},
        headers=_jordan_headers(),
    )
    assert set_res.status_code == 200
    return session_id, exercise_id
