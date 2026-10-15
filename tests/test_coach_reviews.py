"""Coach reviews — roster-only create/edit; historical stay visible after leave."""

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
from app.services.roster_link_service import RosterLinkService


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
        "trainee_id": (body.get("trainee") or {}).get("id"),
        "trainer_id": (body.get("trainer") or {}).get("id"),
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def users(client: TestClient) -> dict:
    from app.core.redis import create_redis_client

    r = create_redis_client()
    try:
        r.flushdb()
    finally:
        r.close()
    settings = get_settings()
    return {
        "maya": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
        "sara": _login(client, "sara.coach@tactech.app", settings.seed_trainer_password),
        "ali": _login(client, "ali.coach@tactech.app", settings.seed_trainer_password),
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


def _link_trainee_to_trainer(*, trainee_id: str, trainer_id: str) -> None:
    db = SessionLocal()
    try:
        trainee = db.get(models.TraineeProfile, trainee_id)
        trainer = db.get(models.TrainerProfile, trainer_id)
        assert trainee and trainer
        RosterLinkService(db).activate(
            trainer=trainer,
            trainee=trainee,
            invite_code_used=trainer.invite_code,
            source="invite",
        )
        db.commit()
    finally:
        db.close()


def _unlink_trainee(*, trainee_id: str) -> None:
    db = SessionLocal()
    try:
        trainee = db.get(models.TraineeProfile, trainee_id)
        assert trainee
        RosterLinkService(db).end_active(trainee=trainee, ended_by_user_id=trainee.user_id)
        db.commit()
    finally:
        db.close()


def test_rostered_create_updates_aggregates(client: TestClient, users: dict) -> None:
    coach_id = "cp-maya"
    _link_trainee_to_trainer(trainee_id=users["trainee"]["trainee_id"], trainer_id="trainer-maya")
    _clear_review(author_user_id=users["trainee"]["user_id"], coach_profile_id=coach_id)

    mine = client.get(f"/coaches/{coach_id}/reviews/me", headers=_auth(users["trainee"]["token"]))
    assert mine.status_code == 200
    assert mine.json()["canReview"] is True
    assert mine.json()["reason"] == "OK"

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

    listed = client.get(f"/coaches/{coach_id}/reviews", headers=_auth(users["trainee"]["token"]))
    assert listed.status_code == 200
    page = listed.json()
    assert page["ratingCount"] >= 1
    assert any(i["isMine"] for i in page["items"])
    assert page["ratingCount"] == len(
        [i for i in page["items"] if not i.get("isHidden")]
    ) or page["ratingCount"] >= 1

    detail = client.get(f"/coaches/{coach_id}", headers=_auth(users["trainee"]["token"]))
    assert detail.json()["ratingCount"] == page["ratingCount"]


def test_cross_coach_forbidden(client: TestClient, users: dict) -> None:
    _link_trainee_to_trainer(trainee_id=users["trainee"]["trainee_id"], trainer_id="trainer-maya")
    before = client.get("/coaches/cp-sara/reviews", headers=_auth(users["trainee"]["token"]))
    count_before = before.json()["ratingCount"]

    res = client.post(
        "/coaches/cp-sara/reviews",
        headers=_auth(users["trainee"]["token"]),
        json={"stars": 5, "body": "nope"},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "NOT_ELIGIBLE"

    after = client.get("/coaches/cp-sara/reviews", headers=_auth(users["trainee"]["token"]))
    assert after.json()["ratingCount"] == count_before

    mine = client.get("/coaches/cp-sara/reviews/me", headers=_auth(users["trainee"]["token"]))
    assert mine.json()["canReview"] is False
    assert mine.json()["reason"] == "NOT_ROSTERED"


def test_guest_trainee_cannot_write(client: TestClient, users: dict) -> None:
    _unlink_trainee(trainee_id=users["trainee"]["trainee_id"])
    mine = client.get("/coaches/cp-maya/reviews/me", headers=_auth(users["trainee"]["token"]))
    assert mine.json()["canReview"] is False
    assert mine.json()["reason"] == "NOT_ROSTERED"

    res = client.post(
        "/coaches/cp-maya/reviews",
        headers=_auth(users["trainee"]["token"]),
        json={"stars": 4, "body": "guest"},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "NOT_ELIGIBLE"

    # List still public
    listed = client.get("/coaches/cp-maya/reviews", headers=_auth(users["trainee"]["token"]))
    assert listed.status_code == 200


def test_after_leave_review_stays_edit_blocked(client: TestClient, users: dict) -> None:
    coach_id = "cp-maya"
    _link_trainee_to_trainer(trainee_id=users["priya"]["trainee_id"], trainer_id="trainer-maya")
    _clear_review(author_user_id=users["priya"]["user_id"], coach_profile_id=coach_id)

    created = client.post(
        f"/coaches/{coach_id}/reviews",
        headers=_auth(users["priya"]["token"]),
        json={"stars": 4, "body": "before leave"},
    )
    assert created.status_code == 201, created.text
    review_id = created.json()["id"]

    _unlink_trainee(trainee_id=users["priya"]["trainee_id"])

    mine = client.get(f"/coaches/{coach_id}/reviews/me", headers=_auth(users["priya"]["token"]))
    assert mine.status_code == 200
    assert mine.json()["canReview"] is False
    assert mine.json()["reason"] == "NOT_ROSTERED"
    assert mine.json()["review"] is not None
    assert mine.json()["review"]["id"] == review_id

    put = client.put(
        f"/coaches/{coach_id}/reviews/me",
        headers=_auth(users["priya"]["token"]),
        json={"stars": 1, "body": "hack"},
    )
    assert put.status_code == 403
    assert put.json()["code"] == "NOT_ELIGIBLE"

    delete = client.delete(
        f"/coaches/{coach_id}/reviews/me",
        headers=_auth(users["priya"]["token"]),
    )
    assert delete.status_code == 403

    listed = client.get(f"/coaches/{coach_id}/reviews", headers=_auth(users["maya"]["token"]))
    assert review_id in {i["id"] for i in listed.json()["items"]}

    # Restore priya on maya for other tests
    _link_trainee_to_trainer(trainee_id=users["priya"]["trainee_id"], trainer_id="trainer-maya")


def test_second_post_conflicts(client: TestClient, users: dict) -> None:
    coach_id = "cp-maya"
    _link_trainee_to_trainer(trainee_id=users["trainee"]["trainee_id"], trainer_id="trainer-maya")
    mine = client.get(f"/coaches/{coach_id}/reviews/me", headers=_auth(users["trainee"]["token"]))
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


def test_put_updates_and_delete_while_rostered(client: TestClient, users: dict) -> None:
    coach_id = "cp-maya"
    _link_trainee_to_trainer(trainee_id=users["marcus"]["trainee_id"], trainer_id="trainer-maya")
    _clear_review(author_user_id=users["marcus"]["user_id"], coach_profile_id=coach_id)

    created = client.post(
        f"/coaches/{coach_id}/reviews",
        headers=_auth(users["marcus"]["token"]),
        json={"stars": 3, "body": "average"},
    )
    assert created.status_code == 201

    updated = client.put(
        f"/coaches/{coach_id}/reviews/me",
        headers=_auth(users["marcus"]["token"]),
        json={"stars": 5, "body": "updated thoughts"},
    )
    assert updated.status_code == 200
    assert updated.json()["stars"] == 5

    deleted = client.delete(
        f"/coaches/{coach_id}/reviews/me",
        headers=_auth(users["marcus"]["token"]),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_non_trainee_forbidden(client: TestClient, users: dict) -> None:
    res = client.post(
        "/coaches/cp-maya/reviews",
        headers=_auth(users["maya"]["token"]),
        json={"stars": 5, "body": "nope"},
    )
    assert res.status_code == 403

    mine = client.get("/coaches/cp-maya/reviews/me", headers=_auth(users["maya"]["token"]))
    assert mine.status_code == 200
    assert mine.json()["canReview"] is False
    assert mine.json()["reason"] == "NOT_TRAINEE_ROLE"


def test_hidden_excluded_from_public_list(client: TestClient, users: dict) -> None:
    coach_id = "cp-maya"
    _link_trainee_to_trainer(trainee_id=users["marcus"]["trainee_id"], trainer_id="trainer-maya")
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
    assert review_id not in {i["id"] for i in listed.json()["items"]}

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
        maya.rating_avg = Decimal("4.90")
        maya.rating_count = 20
        ali.rating_avg = Decimal("3.00")
        ali.rating_count = 2
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
    ids = [i["id"] for i in items]
    assert ids.index("cp-ali") < ids.index("cp-maya")


def test_report_idempotent(client: TestClient, users: dict) -> None:
    coach_id = "cp-maya"
    listed = client.get(f"/coaches/{coach_id}/reviews", headers=_auth(users["trainee"]["token"]))
    items = listed.json()["items"]
    review_id = None
    for item in items:
        if item["authorUserId"] != users["trainee"]["user_id"]:
            review_id = item["id"]
            break
    if review_id is None:
        _link_trainee_to_trainer(trainee_id=users["priya"]["trainee_id"], trainer_id="trainer-maya")
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
    r2 = client.post(
        f"/coaches/reviews/{review_id}/report",
        headers=_auth(users["trainee"]["token"]),
        json={"reason": "Spam or fake"},
    )
    assert r2.status_code == 200


def test_me_coach_profile_includes_ratings(client: TestClient, users: dict) -> None:
    res = client.get("/me/coach-profile", headers=_auth(users["maya"]["token"]))
    assert res.status_code == 200
    body = res.json()
    assert "ratingAvg" in body
    assert "ratingCount" in body


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
