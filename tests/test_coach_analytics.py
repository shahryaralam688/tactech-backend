"""Phase 6 — trainer discovery analytics (views + contacts)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.main import app
from app.repositories.analytics import EVENT_VIEW


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
        "priya": _login(client, "priya@tactech.app", settings.seed_trainee_password),
    }


def _count_events(coach_profile_id: str, event_type: str) -> int:
    db = SessionLocal()
    try:
        return int(
            db.scalar(
                select(func.count())
                .select_from(models.CoachProfileEvent)
                .where(
                    models.CoachProfileEvent.coach_profile_id == coach_profile_id,
                    models.CoachProfileEvent.event_type == event_type,
                )
            )
            or 0
        )
    finally:
        db.close()


def test_owner_reads_analytics_trainee_forbidden(client: TestClient, users: dict) -> None:
    ok = client.get(
        "/me/coach-analytics?periodDays=30",
        headers=_auth(users["trainer"]["token"]),
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["coachProfileId"]
    assert body["periodDays"] == 30
    assert "from" in body and "to" in body
    assert "totals" in body
    assert "series" in body
    assert "viewerUserId" not in str(body)
    assert "email" not in body["totals"]

    forbidden = client.get(
        "/me/coach-analytics",
        headers=_auth(users["trainee"]["token"]),
    )
    assert forbidden.status_code == 403

    # Another trainer only sees their own profile analytics (no cross-access param)
    ali = client.get(
        "/me/coach-analytics?periodDays=7",
        headers=_auth(users["ali"]["token"]),
    )
    assert ali.status_code == 200
    assert ali.json()["coachProfileId"] == "cp-ali"
    assert ali.json()["coachProfileId"] != ok.json()["coachProfileId"]


def test_detail_view_increments_non_owner_only(client: TestClient, users: dict) -> None:
    before = _count_events("cp-maya", EVENT_VIEW)
    # Owner self-view — no increment
    self_v = client.get("/coaches/cp-maya", headers=_auth(users["trainer"]["token"]))
    assert self_v.status_code == 200
    assert _count_events("cp-maya", EVENT_VIEW) == before

    # Trainee view — increments
    other = client.get("/coaches/cp-maya", headers=_auth(users["trainee"]["token"]))
    assert other.status_code == 200
    assert _count_events("cp-maya", EVENT_VIEW) == before + 1


def test_contact_increments(client: TestClient, users: dict) -> None:
    before_c = _count_events("cp-ali", "contact")
    before_cc = _count_events("cp-ali", "contact_created")
    res = client.post(
        "/coaches/cp-ali/contact",
        headers=_auth(users["trainee"]["token"]),
        json={"message": "analytics contact ping"},
    )
    assert res.status_code == 200, res.text
    assert _count_events("cp-ali", "contact") == before_c + 1
    # created may or may not be true if thread existed
    assert _count_events("cp-ali", "contact_created") >= before_cc


def test_unique_viewers_and_series_length(client: TestClient, users: dict) -> None:
    # Two distinct viewers hit Maya detail
    client.get("/coaches/cp-maya", headers=_auth(users["trainee"]["token"]))
    client.get("/coaches/cp-maya", headers=_auth(users["priya"]["token"]))

    res = client.get(
        "/me/coach-analytics?periodDays=7",
        headers=_auth(users["trainer"]["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["series"]) == 7
    assert all(set(d.keys()) >= {"date", "views", "uniqueViewers", "impressions", "contacts"} for d in body["series"])
    assert body["totals"]["uniqueViewers"] >= 1
    assert body["totals"]["views"] >= body["totals"]["uniqueViewers"] or body["totals"]["views"] >= 1

    summary = client.get(
        "/me/coach-analytics/summary?periodDays=7",
        headers=_auth(users["trainer"]["token"]),
    )
    assert summary.status_code == 200
    assert "series" not in summary.json()
    assert summary.json()["totals"]["views"] == body["totals"]["views"]


def test_boost_active_days_partial_period(client: TestClient, users: dict) -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        maya = db.get(models.CoachProfile, "cp-maya")
        assert maya
        for b in db.scalars(
            select(models.CoachBoost).where(models.CoachBoost.user_id == maya.user_id)
        ).all():
            b.status = "expired"
            b.ends_at = now - timedelta(days=60)
            b.provider_payment_id = None
            b.merchant_txn_id = None
        # Boost covering exactly 3 calendar days ending yesterday
        start = (now - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (now - timedelta(days=0)).replace(hour=0, minute=0, second=0, microsecond=0)
        db.add(
            models.CoachBoost(
                id=str(uuid4()),
                user_id=maya.user_id,
                trainer_id=maya.trainer_id,
                product_id="boost.featured.7d",
                tier="featured",
                status="expired",
                starts_at=start,
                ends_at=end,
                amount_minor=0,
                currency="usd",
                source="manual",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    finally:
        db.close()

    res = client.get(
        "/me/coach-analytics?periodDays=30",
        headers=_auth(users["trainer"]["token"]),
    )
    assert res.status_code == 200
    days = res.json()["totals"]["boostActiveDays"]
    assert days >= 3


def test_impressions_deduped(client: TestClient, users: dict) -> None:
    # Clear recent impressions so dedupe window is empty for this viewer
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=20)
        for row in db.scalars(
            select(models.CoachProfileEvent).where(
                models.CoachProfileEvent.viewer_user_id == users["trainee"]["user_id"],
                models.CoachProfileEvent.event_type == "impression",
                models.CoachProfileEvent.coach_profile_id.in_(["cp-sara", "cp-omar"]),
                models.CoachProfileEvent.created_at >= cutoff,
            )
        ).all():
            db.delete(row)
        db.commit()
    finally:
        db.close()

    payload = {"coachProfileIds": ["cp-sara", "cp-omar"], "source": "discover_list"}
    r1 = client.post(
        "/coaches/events/impressions",
        headers=_auth(users["trainee"]["token"]),
        json=payload,
    )
    assert r1.status_code == 200, r1.text
    first = r1.json()["recorded"]
    assert first >= 1

    r2 = client.post(
        "/coaches/events/impressions",
        headers=_auth(users["trainee"]["token"]),
        json=payload,
    )
    assert r2.status_code == 200
    assert r2.json()["recorded"] == 0  # within 15 min window


def test_bad_period_validation(client: TestClient, users: dict) -> None:
    res = client.get(
        "/me/coach-analytics?periodDays=14",
        headers=_auth(users["trainer"]["token"]),
    )
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


def test_reviews_still_work(client: TestClient, users: dict) -> None:
    res = client.get("/coaches/cp-maya/reviews", headers=_auth(users["trainee"]["token"]))
    assert res.status_code == 200
    assert "ratingAvg" in res.json()
