"""Generate reliability: sanitize clamps, id remap, Groq 429."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.ai.providers.text_groq import GroqTextProvider
from app.ai.schemas.workout_plan_out import LlmWorkoutPlan
from app.core.config import Settings, get_settings
from app.core.exceptions import RateLimitError
from app.db import models
from app.db.session import SessionLocal
from app.main import app
from app.services.ai_program_service import sanitize_llm_plan_dict


CATALOG = {
    "ex-squat": "Barbell Squat",
    "ex-pushup": "Push Up",
    "ex-plank": "Plank",
    "ex-ai-bird-dog": "Bird Dog",
    "ex-ai-dead-bug": "Dead Bug",
    "ex-ai-goblet-b": "Goblet Box Squat",
}
VALID = set(CATALOG)


def test_sanitize_reps_and_duration_zero() -> None:
    raw = {
        "title": "Week",
        "focus": "Fit",
        "durationMinutes": 0,
        "level": "Beginner",
        "daysPerWeek": 3,
        "days": [
            {
                "weekday": "Mon",
                "title": "A",
                "focus": "Full",
                "durationMinutes": 0,
                "exercises": [
                    {"exerciseId": "ex-squat", "sets": 0, "reps": 0, "restSeconds": -1},
                ],
            }
        ],
    }
    cleaned, stats = sanitize_llm_plan_dict(raw, valid_ids=VALID, id_to_name=CATALOG)
    assert cleaned is not None
    assert cleaned["durationMinutes"] >= 10
    assert cleaned["days"][0]["durationMinutes"] >= 10
    assert cleaned["days"][0]["exercises"][0]["reps"] >= 1
    assert cleaned["days"][0]["exercises"][0]["sets"] >= 1
    assert cleaned["days"][0]["exercises"][0]["restSeconds"] >= 0
    assert stats["repsClamped"] >= 1
    assert stats["durationClamped"] >= 1
    plan = LlmWorkoutPlan.model_validate(cleaned)
    assert plan.days[0].exercises[0].reps >= 1


def test_sanitize_drops_empty_day_strings() -> None:
    raw = {
        "title": "Week",
        "focus": "Fit",
        "durationMinutes": 45,
        "level": "Beginner",
        "daysPerWeek": 3,
        "days": [
            "",
            None,
            {
                "weekday": "Wed",
                "title": "B",
                "focus": "Push",
                "durationMinutes": 40,
                "exercises": [
                    {"exerciseId": "ex-pushup", "sets": 3, "reps": 10, "restSeconds": 60},
                ],
            },
        ],
    }
    cleaned, stats = sanitize_llm_plan_dict(raw, valid_ids=VALID, id_to_name=CATALOG)
    assert cleaned is not None
    assert stats["daysDropped"] >= 2
    assert len(cleaned["days"]) == 1
    LlmWorkoutPlan.model_validate(cleaned)


def test_sanitize_remaps_unknown_exercise_ids() -> None:
    raw = {
        "title": "Week",
        "focus": "Core",
        "durationMinutes": 40,
        "level": "Beginner",
        "daysPerWeek": 2,
        "days": [
            {
                "weekday": "Mon",
                "title": "Core",
                "focus": "Core",
                "durationMinutes": 40,
                "exercises": [
                    {"exerciseId": "ex-bird-dog", "sets": 3, "reps": 10, "restSeconds": 45},
                    {"exerciseId": "ex-dead-bug", "sets": 3, "reps": 12, "restSeconds": 45},
                    {"exerciseId": "ex-goblet-b", "sets": 3, "reps": 8, "restSeconds": 60},
                ],
            }
        ],
    }
    cleaned, stats = sanitize_llm_plan_dict(raw, valid_ids=VALID, id_to_name=CATALOG)
    assert cleaned is not None
    assert stats["idsRemapped"] == 3
    ids = {ex["exerciseId"] for ex in cleaned["days"][0]["exercises"]}
    assert ids <= VALID
    assert "ex-ai-bird-dog" in ids
    assert "ex-ai-dead-bug" in ids
    assert "ex-ai-goblet-b" in ids
    LlmWorkoutPlan.model_validate(cleaned)


def test_groq_429_then_success() -> None:
    settings = Settings(
        database_url="postgresql://x",
        redis_url="redis://x",
        jwt_secret="x" * 32,
        groq_api_key="gsk_test",
    )
    provider = GroqTextProvider(settings)

    ok_body = {"choices": [{"message": {"content": "hello"}}]}
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, status: int, text: str = "", headers: dict | None = None, data: dict | None = None):
            self.status_code = status
            self.text = text
            self.headers = headers or {}
            self._data = data or {}

        def json(self):
            return self._data

    async def fake_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp(429, text="Rate limit reached. Please try again in 0.1s.", headers={"retry-after": "0"})
        return FakeResp(200, data=ok_body)

    with patch("httpx.AsyncClient") as client_cls:
        instance = AsyncMock()
        instance.post = AsyncMock(side_effect=fake_post)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = instance

        with patch("app.ai.providers.text_groq.asyncio.sleep", new_callable=AsyncMock) as sleep:
            text = asyncio.run(
                provider.complete(
                    [{"role": "user", "content": "hi"}],
                    temperature=0.5,
                    max_tokens=50,
                )
            )
            assert text == "hello"
            assert calls["n"] == 2
            sleep.assert_awaited()


def test_groq_double_429_raises_rate_limited() -> None:
    settings = Settings(
        database_url="postgresql://x",
        redis_url="redis://x",
        jwt_secret="x" * 32,
        groq_api_key="gsk_test",
    )
    provider = GroqTextProvider(settings)

    async def always_429(*args, **kwargs):
        class R:
            status_code = 429
            text = "try again in 2.5s"
            headers = {"retry-after": "3"}

            def json(self):
                return {}

        return R()

    with patch("httpx.AsyncClient") as client_cls:
        instance = AsyncMock()
        instance.post = AsyncMock(side_effect=always_429)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = instance

        with patch("app.ai.providers.text_groq.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RateLimitError) as exc:
                asyncio.run(
                    provider.complete(
                        [{"role": "user", "content": "hi"}],
                        temperature=0.5,
                        max_tokens=50,
                    )
                )
            assert exc.value.status_code == 429
            assert exc.value.code == "RATE_LIMITED"
            assert exc.value.retry_after >= 1


# --- HTTP integration: fixture LLM via gateway mock ---


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
    }


@pytest.fixture(scope="module")
def trainee_user(client: TestClient) -> dict:
    settings = get_settings()
    return _login(client, "trainee@tactech.app", settings.seed_trainee_password)


def _clear_plan_quota(user_id: str) -> None:
    db = SessionLocal()
    try:
        for row in db.query(models.AiPlanGenerationUsage).filter_by(user_id=user_id).all():
            db.delete(row)
        for row in db.query(models.AiEntitlement).filter_by(user_id=user_id).all():
            db.delete(row)
        db.commit()
    finally:
        db.close()


def _unlink(trainee_id: str) -> None:
    db = SessionLocal()
    try:
        profile = db.get(models.TraineeProfile, trainee_id)
        if profile:
            profile.trainer_id = None
            db.add(profile)
        for link in db.query(models.TrainerTraineeLink).filter_by(
            trainee_id=trainee_id, status="active"
        ).all():
            link.status = "ended"
            db.add(link)
        db.commit()
    finally:
        db.close()


def test_generate_sanitizes_bad_llm_json_to_200(client: TestClient, trainee_user: dict) -> None:
    _clear_plan_quota(trainee_user["user_id"])
    _unlink(trainee_user["trainee_id"])
    object.__setattr__(get_settings(), "ai_free_plan_generations", 5)

    bad_json = json.dumps(
        {
            "title": "Broken Week",
            "focus": "General",
            "durationMinutes": 0,
            "level": "Beginner",
            "daysPerWeek": 3,
            "days": [
                "",
                {
                    "weekday": "Mon",
                    "title": "Day 1",
                    "focus": "Full",
                    "durationMinutes": 0,
                    "exercises": [
                        {"exerciseId": "ex-bird-dog", "sets": 0, "reps": 0, "restSeconds": 60},
                        {"exerciseId": "ex-squat", "sets": 3, "reps": 8, "restSeconds": 90},
                    ],
                },
            ],
        }
    )

    async def fake_complete(*args, **kwargs):
        return bad_json

    with patch("app.ai.gateway.AiGateway.complete_text", new=fake_complete):
        res = client.post(
            "/coach/programs/generate",
            headers={"Authorization": f"Bearer {trainee_user['token']}"},
            json={"horizonDays": 7, "notes": "sanitize test"},
        )
    assert res.status_code == 200, res.text
    plan = res.json()
    assert plan["durationMinutes"] >= 10
    assert plan["days"]
    for day in plan["days"]:
        assert isinstance(day, dict)
        for ex in day["exercises"]:
            assert ex["reps"] >= 1
            assert ex["sets"] >= 1
            assert ex["exerciseId"]  # remapped or valid


def test_chat_smoke_still_ok(client: TestClient, trainee_user: dict) -> None:
    object.__setattr__(get_settings(), "ai_text_provider", "mock")
    object.__setattr__(get_settings(), "ai_free_chat_daily_limit", 10)
    # clear daily usage lightly
    db = SessionLocal()
    try:
        for row in db.query(models.AiUsageDaily).filter_by(user_id=trainee_user["user_id"]).all():
            db.delete(row)
        for row in db.query(models.AiEntitlement).filter_by(user_id=trainee_user["user_id"]).all():
            db.delete(row)
        db.commit()
    finally:
        db.close()

    res = client.post(
        "/coach/chat",
        headers={"Authorization": f"Bearer {trainee_user['token']}"},
        json={"message": "hi", "stream": False},
    )
    assert res.status_code == 200, res.text
