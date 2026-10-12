"""Phase 5 — coach reviews & ratings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.main import app
from app.repositories.reviews import ReviewRepository


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
        "trainee": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
        "priya": _login(client, "priya@tactech.app", settings.seed_trainee_password),
        "marcus": _login(client, "marcus@tactech.app", settings.seed_trainee_password),
    }


def _clear_review(*, author_user_id: str, coach_profile_id: str) -> None:
    db = SessionLocal()
    try:
        for row in db.scalars(
            select(models.CoachReview).where(
                models.CoachReview.author_user_id == author_user_id,
                models.CoachReview.coach_profile_id == coach_profile_id,
            )
        ).all():
            db.delete(row)
        db.commit()
        ReviewRepository(db).recompute_aggregates(coach_profile_id)
        db.commit()
    finally:
        db.close()


def _public_coach_id(exclude: set[str] | None = None) -> str:
    exclude = exclude or set()
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(models.CoachProfile).where(models.CoachProfile.is_public.is_(True))
        ).all()
        for r in rows:
            if r.id not in exclude:
                return r.id
        raise AssertionError("no public coach")
    finally:
        db.close()


def test_create_review_updates_aggregates(client: TestClient, users: dict) -> None:
    coach_id = "cp-sara"
    _clear_review(author_user_id=users["trainee"]["user_id"], coach_profile_id=coach_id)

    res = client.post(
        f"/coaches/{coach_id}/reviews",
        headers=_auth(users["trainee"]["token"]),
        json={"stars": 5, "body": "  Great programming and responsive chat.  "},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["stars"] == 5
    assert body["body"] == "Great programming and responsive chat."
    assert body["isMine"] is True
    assert body["authorName"] == "Jordan"
    assert "@" not in body["authorName"]

    listed = client.get(f"/coaches/{coach_id}/reviews", headers=_auth(users["trainee"]["token"]))
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert page["ratingCount"] >= 1
    assert page["ratingAvg"] is not None
    assert any(i["isMine"] for i in page["items"])

    detail = client.get(f"/coaches/{coach_id}", headers=_auth(users["trainee"]["token"]))
    assert detail.status_code == 200
    assert detail.json()["ratingCount"] >= 1
    assert detail.json()["ratingAvg"] is not None


def test_second_post_conflicts(client: TestClient, users: dict) -> None:
    coach_id = "cp-sara"
    # Ensure one exists
    mine = client.get(
        f"/coaches/{coach_id}/reviews/me",
        headers=_auth(users["trainee"]["token"]),
    )
    if mine.json().get("review") is None:
        client.post(
            f"/coaches/{coach_id}/reviews",
            headers=_auth(users["trainee"]["token"]),
            json={"stars": 4, "body": "ok"},
        )
    again = client.post(
        f"/coaches/{coach_id}/reviews",
        headers=_auth(users["trainee"]["token"]),
        json={"stars": 3, "body": "dup"},
    )
    assert again.status_code == 409
    assert again.json()["code"] == "CONFLICT"


def test_put_updates_and_delete_clears(client: TestClient, users: dict) -> None:
    coach_id = "cp-omar"
    _clear_review(author_user_id=users["trainee"]["user_id"], coach_profile_id=coach_id)
    created = client.post(
        f"/coaches/{coach_id}/reviews",
        headers=_auth(users["trainee"]["token"]),
        json={"stars": 3, "body": "average"},
    )
    assert created.status_code == 201

    updated = client.put(
        f"/coaches/{coach_id}/reviews/me",
        headers=_auth(users["trainee"]["token"]),
        json={"stars": 5, "body": "updated thoughts"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["stars"] == 5
    assert updated.json()["body"] == "updated thoughts"

    deleted = client.delete(
        f"/coaches/{coach_id}/reviews/me",
        headers=_auth(users["trainee"]["token"]),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    mine = client.get(
        f"/coaches/{coach_id}/reviews/me",
        headers=_auth(users["trainee"]["token"]),
    )
    assert mine.status_code == 200
    assert mine.json()["review"] is None


def test_non_trainee_forbidden(client: TestClient, users: dict) -> None:
    res = client.post(
        "/coaches/cp-maya/reviews",
        headers=_auth(users["trainer"]["token"]),
        json={"stars": 5, "body": "nope"},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


def test_hidden_excluded_from_public_list(client: TestClient, users: dict) -> None:
    coach_id = "cp-ali"
    _clear_review(author_user_id=users["marcus"]["user_id"], coach_profile_id=coach_id)
    created = client.post(
        f"/coaches/{coach_id}/reviews",
        headers=_auth(users["marcus"]["token"]),
        json={"stars": 1, "body": "spammy"},
    )
    assert created.status_code == 201, created.text
    review_id = created.json()["id"]

    db = SessionLocal()
    try:
        row = db.get(models.CoachReview, review_id)
        assert row
        row.is_hidden = True
        ReviewRepository(db).recompute_aggregates(coach_id)
        db.commit()
    finally:
        db.close()

    listed = client.get(f"/coaches/{coach_id}/reviews", headers=_auth(users["priya"]["token"]))
    assert listed.status_code == 200
    ids = {i["id"] for i in listed.json()["items"]}
    assert review_id not in ids

    # Author can still see own hidden
    author_list = client.get(
        f"/coaches/{coach_id}/reviews",
        headers=_auth(users["marcus"]["token"]),
    )
    assert review_id in {i["id"] for i in author_list.json()["items"]}


def test_discovery_sort_boost_then_rating(client: TestClient, users: dict) -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        maya = db.get(models.CoachProfile, "cp-maya")
        ali = db.get(models.CoachProfile, "cp-ali")
        assert maya and ali
        # Maya: high rating, no boost
        maya.rating_avg = Decimal("4.90")
        maya.rating_count = 20
        # Ali: lower rating but will get boost
        ali.rating_avg = Decimal("3.00")
        ali.rating_count = 2
        # Clear maya boosts; grant ali boost
        for b in db.scalars(
            select(models.CoachBoost).where(
                models.CoachBoost.user_id.in_([maya.user_id, ali.user_id])
            )
        ).all():
            b.status = "expired"
            b.ends_at = now - timedelta(days=1)
            b.provider_payment_id = None
            b.merchant_txn_id = None
        db.add(
            models.CoachBoost(
                id=str(uuid4()),
                user_id=ali.user_id,
                trainer_id=ali.trainer_id,
                product_id="boost.featured.7d",
                tier="featured",
                status="active",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(days=3),
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

    res = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
    assert res.status_code == 200
    items = res.json()["items"]
    assert items
    # Boosted Ali should rank above higher-rated Maya
    ids = [i["id"] for i in items]
    assert ids.index("cp-ali") < ids.index("cp-maya")
    assert items[0]["boostActive"] is True or "cp-ali" in ids[:2]


def test_report_idempotent(client: TestClient, users: dict) -> None:
    coach_id = "cp-maya"
    # Use seed review if present, else create with priya
    listed = client.get(f"/coaches/{coach_id}/reviews", headers=_auth(users["trainee"]["token"]))
    items = listed.json()["items"]
    review_id = None
    for item in items:
        if item["authorUserId"] != users["trainee"]["user_id"]:
            review_id = item["id"]
            break
    if review_id is None:
        _clear_review(author_user_id=users["priya"]["user_id"], coach_profile_id=coach_id)
        created = client.post(
            f"/coaches/{coach_id}/reviews",
            headers=_auth(users["priya"]["token"]),
            json={"stars": 4, "body": "report target"},
        )
        review_id = created.json()["id"]

    r1 = client.post(
        f"/coaches/reviews/{review_id}/report",
        headers=_auth(users["trainee"]["token"]),
        json={"reason": "Spam or fake"},
    )
    assert r1.status_code == 200
    assert r1.json()["reported"] is True
    r2 = client.post(
        f"/coaches/reviews/{review_id}/report",
        headers=_auth(users["trainee"]["token"]),
        json={"reason": "Spam or fake"},
    )
    assert r2.status_code == 200
    assert r2.json()["reported"] is True


def test_me_coach_profile_includes_ratings(client: TestClient, users: dict) -> None:
    res = client.get("/me/coach-profile", headers=_auth(users["trainer"]["token"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert "ratingAvg" in body
    assert "ratingCount" in body
    assert isinstance(body["ratingCount"], int)


def test_contact_still_works(client: TestClient, users: dict) -> None:
    coaches = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
    coach_id = coaches.json()["items"][0]["id"]
    res = client.post(
        f"/coaches/{coach_id}/contact",
        headers=_auth(users["trainee"]["token"]),
        json={},
    )
    assert res.status_code == 200, res.text
    assert res.json()["threadId"]
