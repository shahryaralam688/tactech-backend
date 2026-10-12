"""Live Sandow Score series — trainee / boost / roster (no random scores)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.main import app
from app.repositories.analytics import EVENT_CONTACT, EVENT_IMPRESSION, EVENT_VIEW
from app.services.sandow_service import boost_day_raw, trainee_day_score


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
    return {
        "trainer": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
        "ali": _login(client, "ali.coach@tactech.app", settings.seed_trainer_password),
        "trainee": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
    }


def test_formula_stable_no_random() -> None:
    assert trainee_day_score(form_scores=[80, 90], log_count=3) == 85
    assert trainee_day_score(form_scores=[], log_count=2) == 86  # 70 + 16
    assert trainee_day_score(form_scores=[], log_count=5) == 100
    assert trainee_day_score(form_scores=[], log_count=0) == 0
    assert boost_day_raw(views=10, contacts=2, impressions=40) == 10 + 10 + 10


def test_trainee_week_has_explicit_zeros(client: TestClient, users: dict) -> None:
    res = client.get(
        "/me/sandow-score?period=week",
        headers=_auth(users["trainee"]["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["role"] == "trainee"
    assert body["mode"] == "workout_performance"
    assert body["period"] == "week"
    assert body["title"] == "Sandow Score"
    assert len(body["points"]) == 7
    assert "from" in body and "to" in body
    assert body["from"] <= body["to"]
    # Every day present; scores in 0–100; no random-looking fill without activity
    for p in body["points"]:
        assert "date" in p and "label" in p
        assert 0 <= p["score"] <= 100
        assert "views" not in p
    assert 0 <= body["summaryScore"] <= 100
    # Seed has a form report today-ish for jordan — at least one non-zero is OK but not required


def test_trainee_month_30_points(client: TestClient, users: dict) -> None:
    res = client.get(
        "/me/sandow-score?period=month",
        headers=_auth(users["trainee"]["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["period"] == "month"
    assert len(body["points"]) == 30
    assert body["summaryLabel"] == "Last 30 days"


def test_bad_period_400(client: TestClient, users: dict) -> None:
    res = client.get(
        "/me/sandow-score?period=year",
        headers=_auth(users["trainee"]["token"]),
    )
    assert res.status_code == 400
    assert res.json().get("code") == "VALIDATION_ERROR"


def test_trainer_free_roster_mode(client: TestClient, users: dict) -> None:
    """Ensure Ali (likely no boost) gets roster_performance with traineeCount."""
    db = SessionLocal()
    try:
        # Clear any active boost for Ali so mode is deterministic
        ali_user = db.scalars(
            select(models.User).where(models.User.email == "ali.coach@tactech.app")
        ).first()
        assert ali_user is not None
        for b in db.scalars(
            select(models.CoachBoost).where(models.CoachBoost.user_id == ali_user.id)
        ).all():
            if b.status == "active":
                b.status = "expired"
                b.ends_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    res = client.get(
        "/me/sandow-score?period=week",
        headers=_auth(users["ali"]["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["role"] == "trainer"
    assert body["mode"] == "roster_performance"
    assert body["boostActive"] is False
    assert "traineeCount" in body
    assert len(body["points"]) == 7
    for p in body["points"]:
        assert 0 <= p["score"] <= 100
        assert "activeTrainees" in p
        assert "sessionsLogged" in p


def test_trainer_boost_mode_from_analytics(client: TestClient, users: dict) -> None:
    db = SessionLocal()
    try:
        maya = db.scalars(
            select(models.User).where(models.User.email == "trainer@tactech.app")
        ).first()
        assert maya is not None
        trainer = db.scalars(
            select(models.TrainerProfile).where(models.TrainerProfile.user_id == maya.id)
        ).first()
        assert trainer is not None
        # Expire existing actives then grant fresh boost
        for b in db.scalars(
            select(models.CoachBoost).where(models.CoachBoost.user_id == maya.id)
        ).all():
            if b.status == "active":
                b.status = "expired"
                b.ends_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        now = datetime.now(timezone.utc)
        db.add(
            models.CoachBoost(
                id=str(uuid4()),
                user_id=maya.id,
                trainer_id=trainer.id,
                product_id="boost.featured.7d",
                tier="featured",
                status="active",
                starts_at=now - timedelta(days=1),
                ends_at=now + timedelta(days=6),
                amount_minor=0,
                currency="usd",
                source="manual",
                created_at=now,
                updated_at=now,
            )
        )
        # Seed discovery events across two days for cp-maya
        profile = db.scalars(
            select(models.CoachProfile).where(models.CoachProfile.trainer_id == trainer.id)
        ).first()
        assert profile is not None
        for i, (etype, hours_ago) in enumerate(
            [
                (EVENT_VIEW, 2),
                (EVENT_VIEW, 3),
                (EVENT_CONTACT, 2),
                (EVENT_IMPRESSION, 26),
                (EVENT_IMPRESSION, 27),
                (EVENT_VIEW, 26),
            ]
        ):
            db.add(
                models.CoachProfileEvent(
                    id=f"sandow-ev-{uuid4().hex[:12]}",
                    coach_profile_id=profile.id,
                    trainer_id=trainer.id,
                    viewer_user_id=users["trainee"]["user_id"],
                    event_type=etype,
                    created_at=now - timedelta(hours=hours_ago),
                    meta={"source": "sandow_test", "i": i},
                )
            )
        db.commit()
    finally:
        db.close()

    res = client.get(
        "/me/sandow-score?period=week",
        headers=_auth(users["trainer"]["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["role"] == "trainer"
    assert body["mode"] == "boost_analytics"
    assert body["boostActive"] is True
    assert body["title"] == "Boost reach"
    assert len(body["points"]) == 7
    # At least one day should have engagement metrics / non-zero score after seeding
    assert any(p.get("views", 0) > 0 or p.get("impressions", 0) > 0 for p in body["points"])
    assert any(p["score"] > 0 for p in body["points"])
    for p in body["points"]:
        assert "views" in p and "contacts" in p and "impressions" in p
        assert 0 <= p["score"] <= 100


def test_unauthorized(client: TestClient) -> None:
    res = client.get("/me/sandow-score")
    assert res.status_code == 401
