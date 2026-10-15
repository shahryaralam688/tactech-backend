"""AI Gateway + freemium: capabilities, quotas, vision stubs, solo generate."""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db import models
from app.main import app
from app.services.ai_billing_service import AiBillingService


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    user = body["user"]
    trainee = body.get("trainee") or {}
    trainer = body.get("trainer") or {}
    return {
        "token": body["accessToken"],
        "user_id": user["id"],
        "trainee_id": trainee.get("id"),
        "trainer_id": trainer.get("id"),
    }


@pytest.fixture(scope="module")
def users(client: TestClient) -> dict:
    settings = get_settings()
    return {
        "trainee": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
        "trainer": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _clear_ai(user_id: str) -> None:
    db = SessionLocal()
    try:
        for row in db.query(models.AiEntitlement).filter_by(user_id=user_id).all():
            db.delete(row)
        for row in db.query(models.AiUsageWeekly).filter_by(user_id=user_id).all():
            db.delete(row)
        for row in db.query(models.AiUsageDaily).filter_by(user_id=user_id).all():
            db.delete(row)
        for row in db.query(models.AiPlanGenerationUsage).filter_by(user_id=user_id).all():
            db.delete(row)
        db.commit()
    finally:
        db.close()


def test_capabilities_authenticated(client: TestClient, users: dict) -> None:
    res = client.get("/coach/ai/capabilities", headers=_auth(users["trainee"]["token"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert "textChat" in body
    assert "structuredPlanJson" in body
    assert body["visionPose"] is False
    assert body["visionFood"] is False
    assert body["visionPoseProvider"] == "stub"
    assert body["visionFoodProvider"] == "stub"
    assert body["textProvider"] in {"gemini", "groq", "openai", "mock", "auto"}
    assert isinstance(body["freeChatDailyLimit"], int)
    assert isinstance(body["freePlanGenerations"], int)


def test_vision_pose_stub_501(client: TestClient, users: dict) -> None:
    res = client.post(
        "/coach/vision/pose",
        headers=_auth(users["trainee"]["token"]),
        files={"image": ("pose.jpg", BytesIO(b"fake-image"), "image/jpeg")},
    )
    assert res.status_code == 501, res.text
    body = res.json()
    assert body["code"] == "AI_CAPABILITY_UNAVAILABLE"
    assert body["capability"] == "visionPose"


def test_vision_food_stub_501(client: TestClient, users: dict) -> None:
    res = client.post(
        "/coach/vision/food",
        headers=_auth(users["trainee"]["token"]),
        files={"image": ("food.jpg", BytesIO(b"fake-image"), "image/jpeg")},
    )
    assert res.status_code == 501, res.text
    body = res.json()
    assert body["code"] == "AI_CAPABILITY_UNAVAILABLE"
    assert body["capability"] == "visionFood"


def test_chat_daily_quota_402(client: TestClient, users: dict) -> None:
    _clear_ai(users["trainee"]["user_id"])
    settings = get_settings()
    object.__setattr__(settings, "ai_free_tease_messages_per_week", 0)
    object.__setattr__(settings, "ai_free_chat_daily_limit", 1)
    object.__setattr__(settings, "ai_text_provider", "mock")

    first = client.post(
        "/coach/chat",
        headers=_auth(users["trainee"]["token"]),
        json={"message": "hello", "stream": False},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/coach/chat",
        headers=_auth(users["trainee"]["token"]),
        json={"message": "again", "stream": False},
    )
    assert second.status_code == 402, second.text
    assert second.json()["code"] == "AI_QUOTA_EXCEEDED"


def test_solo_generate_once_then_402(client: TestClient, users: dict) -> None:
    trainee = users["trainee"]
    _clear_ai(trainee["user_id"])
    settings = get_settings()
    object.__setattr__(settings, "ai_text_provider", "mock")
    object.__setattr__(settings, "ai_free_plan_generations", 1)

    # Ensure no trainer link
    db = SessionLocal()
    try:
        profile = db.get(models.TraineeProfile, trainee["trainee_id"])
        if profile:
            profile.trainer_id = None
            db.add(profile)
        for link in db.query(models.TrainerTraineeLink).filter_by(
            trainee_id=trainee["trainee_id"], status="active"
        ).all():
            link.status = "ended"
            db.add(link)
        db.commit()
    finally:
        db.close()

    first = client.post(
        "/coach/programs/generate",
        headers=_auth(trainee["token"]),
        json={"horizonDays": 7, "notes": "test"},
    )
    assert first.status_code == 200, first.text
    plan = first.json()
    assert plan["title"]
    assert plan["days"]
    for day in plan["days"]:
        for ex in day["exercises"]:
            assert ex["exerciseId"]

    second = client.post(
        "/coach/programs/generate",
        headers=_auth(trainee["token"]),
        json={"horizonDays": 7},
    )
    assert second.status_code == 402, second.text
    assert second.json()["code"] == "AI_QUOTA_EXCEEDED"


def test_generate_has_trainer_409(client: TestClient, users: dict) -> None:
    trainee = users["trainee"]
    trainer = users["trainer"]
    _clear_ai(trainee["user_id"])
    object.__setattr__(get_settings(), "ai_text_provider", "mock")
    object.__setattr__(get_settings(), "ai_free_plan_generations", 5)

    db = SessionLocal()
    try:
        profile = db.get(models.TraineeProfile, trainee["trainee_id"])
        assert profile is not None
        profile.trainer_id = trainer["trainer_id"]
        db.add(profile)
        db.commit()
    finally:
        db.close()

    res = client.post(
        "/coach/programs/generate",
        headers=_auth(trainee["token"]),
        json={"horizonDays": 7},
    )
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "HAS_TRAINER"

    # cleanup
    db = SessionLocal()
    try:
        profile = db.get(models.TraineeProfile, trainee["trainee_id"])
        if profile:
            profile.trainer_id = None
            db.add(profile)
            db.commit()
    finally:
        db.close()


def test_chat_sse_still_works_with_entitlement(client: TestClient, users: dict) -> None:
    settings = get_settings()
    object.__setattr__(settings, "ai_text_provider", "mock")
    db = SessionLocal()
    try:
        AiBillingService(db, settings).grant_manual(user_id=users["trainee"]["user_id"], days=7)
    finally:
        db.close()

    res = client.post(
        "/coach/chat",
        headers=_auth(users["trainee"]["token"]),
        json={"message": "stream please", "stream": True},
    )
    assert res.status_code == 200, res.text
    assert "text/event-stream" in (res.headers.get("content-type") or "")
    assert "data:" in res.text
