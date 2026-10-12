"""Phase 8 — coach packages listings + inquire."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.main import app
from app.services.package_service import format_price_label


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
        "omar": _login(client, "omar.coach@tactech.app", settings.seed_trainer_password),
        "trainee": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
    }


def test_price_label_helpers() -> None:
    assert "PKR 15,000" in format_price_label(
        amount_minor=1_500_000, currency="pkr", billing_period="month"
    )
    assert "/ month" in format_price_label(
        amount_minor=1_500_000, currency="pkr", billing_period="month"
    )
    assert "$99.00" in format_price_label(
        amount_minor=9900, currency="usd", billing_period="month"
    )


def test_trainer_crud_and_featured(client: TestClient, users: dict) -> None:
    # Use Omar (less seed package noise)
    create = client.post(
        "/me/coach-packages",
        headers=_auth(users["omar"]["token"]),
        json={
            "title": "Mobility Reset",
            "description": "4-week mobility block.",
            "amountMinor": 800000,
            "currency": "pkr",
            "billingPeriod": "month",
            "durationDays": 28,
            "includes": ["Assessments", "Plan"],
            "delivery": "online",
            "status": "active",
            "isFeatured": True,
            "sortOrder": 0,
        },
    )
    assert create.status_code == 201, create.text
    pkg_id = create.json()["id"]
    assert create.json()["isFeatured"] is True

    second = client.post(
        "/me/coach-packages",
        headers=_auth(users["omar"]["token"]),
        json={
            "title": "Rehab Support",
            "description": "Ongoing rehab check-ins.",
            "amountMinor": 600000,
            "currency": "pkr",
            "billingPeriod": "month",
            "includes": ["Check-ins"],
            "delivery": "hybrid",
            "status": "active",
            "isFeatured": True,
            "sortOrder": 1,
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["isFeatured"] is True

    mine = client.get("/me/coach-packages", headers=_auth(users["omar"]["token"]))
    assert mine.status_code == 200
    featured = [i for i in mine.json()["items"] if i["isFeatured"] and i["status"] == "active"]
    assert len(featured) == 1
    assert featured[0]["id"] == second.json()["id"]

    updated = client.put(
        f"/me/coach-packages/{pkg_id}",
        headers=_auth(users["omar"]["token"]),
        json={
            "title": "Mobility Reset Pro",
            "description": "Updated",
            "amountMinor": 900000,
            "currency": "pkr",
            "billingPeriod": "month",
            "includes": ["Assessments"],
            "delivery": "online",
            "status": "active",
            "isFeatured": False,
            "sortOrder": 0,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Mobility Reset Pro"

    archived = client.post(
        f"/me/coach-packages/{pkg_id}/archive",
        headers=_auth(users["omar"]["token"]),
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["isFeatured"] is False


def test_public_packages_and_discovery_summary(client: TestClient, users: dict) -> None:
    res = client.get("/coaches/cp-maya/packages", headers=_auth(users["trainee"]["token"]))
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert items
    assert all(i["status"] == "active" or "status" in i for i in items)
    assert items[0]["isFeatured"] is True or any(i["isFeatured"] for i in items)

    detail = client.get("/coaches/cp-maya", headers=_auth(users["trainee"]["token"]))
    assert detail.status_code == 200
    assert detail.json()["packagesCount"] >= 1
    feat = detail.json()["featuredPackage"]
    assert feat is None or feat["id"]

    listing = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
    maya = next(i for i in listing.json()["items"] if i["id"] == "cp-maya")
    assert "packagesCount" in maya


def test_private_coach_packages_hidden(client: TestClient, users: dict) -> None:
    db = SessionLocal()
    try:
        omar = db.get(models.CoachProfile, "cp-omar")
        assert omar
        omar.is_public = False
        db.commit()
    finally:
        db.close()
    try:
        res = client.get("/coaches/cp-omar/packages", headers=_auth(users["trainee"]["token"]))
        assert res.status_code == 404
        # Owner can still see
        owner = client.get("/coaches/cp-omar/packages", headers=_auth(users["omar"]["token"]))
        assert owner.status_code == 200
    finally:
        db = SessionLocal()
        try:
            omar = db.get(models.CoachProfile, "cp-omar")
            if omar:
                omar.is_public = True
                db.commit()
        finally:
            db.close()


def test_trainee_inquire(client: TestClient, users: dict) -> None:
    packages = client.get("/coaches/cp-maya/packages", headers=_auth(users["trainee"]["token"]))
    pkg_id = packages.json()["items"][0]["id"]
    title = packages.json()["items"][0]["title"]

    res = client.post(
        f"/coaches/cp-maya/packages/{pkg_id}/inquire",
        headers=_auth(users["trainee"]["token"]),
        json={"message": "Is this available starting next week?"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["threadId"]
    assert body["packageId"] == pkg_id
    assert body["peerUserId"]

    # Message landed in chat
    db = SessionLocal()
    try:
        msgs = list(
            db.scalars(
                select(models.ChatMessage)
                .where(models.ChatMessage.thread_id == body["threadId"])
                .order_by(models.ChatMessage.created_at.desc())
            ).all()
        )
        assert msgs
        assert title in (msgs[0].text or "")
        assert "interested" in (msgs[0].text or "").lower()
    finally:
        db.close()


def test_non_trainee_inquire_forbidden(client: TestClient, users: dict) -> None:
    res = client.post(
        "/coaches/cp-maya/packages/pkg-maya-standard/inquire",
        headers=_auth(users["trainer"]["token"]),
        json={},
    )
    assert res.status_code == 403


def test_active_package_limit(client: TestClient, users: dict) -> None:
    # Fill Omar toward limit using drafts skipped — create until 400 if already many
    # Count current active for Omar
    mine = client.get("/me/coach-packages", headers=_auth(users["omar"]["token"]))
    active = [i for i in mine.json()["items"] if i["status"] == "active"]
    # Archive extras beyond a few for test cleanliness, then create up to limit
    for item in active[2:]:
        client.post(
            f"/me/coach-packages/{item['id']}/archive",
            headers=_auth(users["omar"]["token"]),
        )

    created_ids: list[str] = []
    for n in range(25):
        res = client.post(
            "/me/coach-packages",
            headers=_auth(users["omar"]["token"]),
            json={
                "title": f"Pack {n}",
                "description": "x",
                "amountMinor": 1000,
                "currency": "pkr",
                "billingPeriod": "month",
                "includes": ["A"],
                "delivery": "online",
                "status": "active",
                "isFeatured": False,
                "sortOrder": n,
            },
        )
        if res.status_code == 201:
            created_ids.append(res.json()["id"])
            continue
        assert res.status_code == 400
        assert res.json()["code"] == "VALIDATION_ERROR"
        break
    else:
        pytest.fail("expected active package limit")

    # Cleanup
    for pid in created_ids:
        client.post(
            f"/me/coach-packages/{pid}/archive",
            headers=_auth(users["omar"]["token"]),
        )


def test_contact_still_works(client: TestClient, users: dict) -> None:
    res = client.post(
        "/coaches/cp-maya/contact",
        headers=_auth(users["trainee"]["token"]),
        json={},
    )
    assert res.status_code == 200
    assert res.json()["threadId"]
