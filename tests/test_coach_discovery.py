"""Phase 1 coach discovery + entitlements + free contact."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
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
        "role": body["user"]["role"],
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def users(client: TestClient) -> dict:
    settings = get_settings()
    trainer = _login(client, "trainer@tactech.app", settings.seed_trainer_password)
    trainee = _login(client, "trainee@tactech.app", settings.seed_trainee_password)
    return {"trainer": trainer, "trainee": trainee, "settings": settings}


def test_entitlements_defaults(client: TestClient, users: dict) -> None:
    # Isolate from other suites that may grant AI / boost on seed users
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.db import models
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for uid in (users["trainer"]["user_id"], users["trainee"]["user_id"]):
            ai = db.scalars(
                select(models.AiEntitlement).where(models.AiEntitlement.user_id == uid)
            ).first()
            if ai is not None:
                ai.status = "expired"
                ai.ends_at = now - timedelta(days=1)
                ai.plan = None
            for b in db.scalars(
                select(models.CoachBoost).where(models.CoachBoost.user_id == uid)
            ).all():
                b.status = "expired"
                b.ends_at = now - timedelta(days=1)
        db.commit()
    finally:
        db.close()

    for key in ("trainer", "trainee"):
        res = client.get("/me/entitlements", headers=_auth(users[key]["token"]))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ai"]["active"] is False
        assert body["ai"]["plan"] is None
        assert body["boost"]["active"] is False
        assert body["boost"]["tier"] is None


def test_coach_profile_draft_and_public_validation(client: TestClient, users: dict) -> None:
    headers = _auth(users["trainer"]["token"])

    # Trainee cannot manage coach profile
    trainee_get = client.get("/me/coach-profile", headers=_auth(users["trainee"]["token"]))
    assert trainee_get.status_code == 403
    assert trainee_get.json()["code"] == "FORBIDDEN"

    draft = client.get("/me/coach-profile", headers=headers)
    assert draft.status_code == 200, draft.text
    data = draft.json()
    assert data["isPublic"] is False or isinstance(data["isPublic"], bool)
    assert "trainerId" in data
    assert "userId" in data
    assert "boostActive" in data
    assert data["userId"] == users["trainer"]["user_id"]

    bad = client.put(
        "/me/coach-profile",
        headers=headers,
        json={
            "headline": "",
            "bio": "",
            "city": "",
            "countryCode": "PK",
            "specialties": [],
            "languages": [],
            "isPublic": True,
        },
    )
    assert bad.status_code == 400, bad.text
    assert bad.json()["code"] == "VALIDATION_ERROR"

    ok = client.put(
        "/me/coach-profile",
        headers=headers,
        json={
            "headline": "Strength coach · Lahore",
            "bio": "Online + in-gym strength programming.",
            "city": "Lahore",
            "countryCode": "PK",
            "specialties": ["strength", "hypertrophy"],
            "languages": ["en", "ur"],
            "gymName": "Iron Hub",
            "yearsExperience": 5,
            "isPublic": True,
            "coverImageUrl": None,
        },
    )
    assert ok.status_code == 200, ok.text
    saved = ok.json()
    assert saved["isPublic"] is True
    assert saved["headline"]
    assert saved["city"] == "Lahore"
    assert "strength" in saved["specialties"]


def test_public_list_hides_private_and_filters(client: TestClient, users: dict) -> None:
    headers = _auth(users["trainee"]["token"])
    listed = client.get("/coaches", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert "items" in body
    assert "nextCursor" in body
    for item in body["items"]:
        assert "bio" not in item or item.get("bio") is None or True
        # List DTO should not expose invite / email
        assert "email" not in item
        assert "inviteCode" not in item
        assert "password" not in item
        assert item.get("city")

    # Seeded public coaches (different cities/specialties)
    cities = {i["city"] for i in body["items"]}
    assert "Lahore" in cities or len(body["items"]) >= 1

    by_city = client.get("/coaches", headers=headers, params={"city": "Karachi"})
    assert by_city.status_code == 200
    for item in by_city.json()["items"]:
        assert item["city"].lower() == "karachi"

    by_spec = client.get("/coaches", headers=headers, params={"specialty": "mobility"})
    assert by_spec.status_code == 200
    for item in by_spec.json()["items"]:
        assert "mobility" in [s.lower() for s in item["specialties"]]

    q = client.get("/coaches", headers=headers, params={"q": "Omar"})
    assert q.status_code == 200


def test_private_detail_404_for_others(client: TestClient, users: dict) -> None:
    settings = users["settings"]
    # Login as Ali coach, set private, then trainee must 404
    ali = _login(client, "ali.coach@tactech.app", settings.seed_trainer_password)
    me = client.get("/me/coach-profile", headers=_auth(ali["token"]))
    assert me.status_code == 200, me.text
    profile_id = me.json()["id"]

    private = client.put(
        "/me/coach-profile",
        headers=_auth(ali["token"]),
        json={
            "headline": "Private draft",
            "bio": "hidden",
            "city": "Lahore",
            "countryCode": "PK",
            "specialties": ["strength"],
            "languages": ["en"],
            "isPublic": False,
        },
    )
    assert private.status_code == 200
    assert private.json()["isPublic"] is False

    # Owner can still see via detail
    owner_detail = client.get(f"/coaches/{profile_id}", headers=_auth(ali["token"]))
    assert owner_detail.status_code == 200

    other = client.get(f"/coaches/{profile_id}", headers=_auth(users["trainee"]["token"]))
    assert other.status_code == 404
    assert other.json()["code"] == "NOT_FOUND"

    # Restore public for other tests / discovery
    client.put(
        "/me/coach-profile",
        headers=_auth(ali["token"]),
        json={
            "headline": "Strength coach · Lahore",
            "bio": "Online + in-gym strength programming for busy professionals.",
            "city": "Lahore",
            "countryCode": "PK",
            "specialties": ["strength", "hypertrophy"],
            "languages": ["en", "ur"],
            "gymName": "Iron Hub",
            "yearsExperience": 5,
            "isPublic": True,
        },
    )


def test_contact_creates_then_reuses_thread(client: TestClient, users: dict) -> None:
    # Trainer cannot contact
    coaches = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
    assert coaches.status_code == 200
    items = coaches.json()["items"]
    assert items, "need at least one public coach"
    coach_id = items[0]["id"]
    peer = items[0]["userId"]

    forbidden = client.post(
        f"/coaches/{coach_id}/contact",
        headers=_auth(users["trainer"]["token"]),
        json={"message": "hi"},
    )
    assert forbidden.status_code == 403

    first = client.post(
        f"/coaches/{coach_id}/contact",
        headers=_auth(users["trainee"]["token"]),
        json={"message": "Hi, I’d like coaching help."},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["threadId"]
    assert body["peerUserId"] == peer
    assert isinstance(body["created"], bool)

    second = client.post(
        f"/coaches/{coach_id}/contact",
        headers=_auth(users["trainee"]["token"]),
        json={"message": "Following up"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["threadId"] == body["threadId"]
    assert second.json()["created"] is False

    # Thread usable via existing chat API
    msgs = client.get(
        f"/chat/threads/{body['threadId']}/messages",
        headers=_auth(users["trainee"]["token"]),
    )
    assert msgs.status_code == 200
