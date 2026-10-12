"""GET /me assessment + onboarding flags for iOS gates."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_me_includes_completion_flags(client: TestClient) -> None:
    settings = get_settings()
    login = client.post(
        "/auth/login",
        json={"email": "trainee@tactech.app", "password": settings.seed_trainee_password},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert "assessmentCompleted" in body
    assert "onboardingCompleted" in body
    assert isinstance(body["assessmentCompleted"], bool)
    assert isinstance(body["onboardingCompleted"], bool)

    me = client.get("/me", headers=_auth(body["accessToken"]))
    assert me.status_code == 200, me.text
    data = me.json()
    assert "assessmentCompleted" in data
    assert "onboardingCompleted" in data
    assert "user" in data
    assert data["user"]["role"] == "trainee"


def test_profile_and_support_and_content(client: TestClient) -> None:
    settings = get_settings()
    login = client.post(
        "/auth/login",
        json={"email": "trainer@tactech.app", "password": settings.seed_trainer_password},
    )
    token = login.json()["accessToken"]
    headers = _auth(token)

    profile = client.get("/me/profile", headers=headers)
    assert profile.status_code == 200, profile.text
    assert "user" in profile.json()
    assert "profile" in profile.json()

    faq = client.get("/content/faq", headers=headers)
    assert faq.status_code == 200
    assert len(faq.json()) >= 1

    about = client.get("/content/about", headers=headers)
    assert about.status_code == 200
    assert about.json()["brandName"] == "TacTech"

    conv = client.post("/support/conversations", headers=headers)
    assert conv.status_code == 201, conv.text
    cid = conv.json()["id"]
    msg = client.post(
        f"/support/conversations/{cid}/messages",
        headers=headers,
        json={"text": "Need help with invite code"},
    )
    assert msg.status_code == 201, msg.text
    assert msg.json()["sender"] == "user"
    assert msg.json()["text"]

    listed = client.get(f"/support/conversations/{cid}/messages", headers=headers)
    assert listed.status_code == 200
    senders = {m["sender"] for m in listed.json()}
    assert "user" in senders
    assert "support" in senders  # welcome mapped from system


def test_templates_and_prefs(client: TestClient) -> None:
    settings = get_settings()
    login = client.post(
        "/auth/login",
        json={"email": "trainer@tactech.app", "password": settings.seed_trainer_password},
    )
    headers = _auth(login.json()["accessToken"])

    templates = client.get("/trainer/exercise-templates", headers=headers)
    assert templates.status_code == 200

    prefs = client.get("/me/preferences/language", headers=headers)
    assert prefs.status_code == 200
    assert "languageCode" in prefs.json()

    sec = client.put(
        "/me/preferences/security",
        headers=headers,
        json={"twoFactor": False, "googleAuth": False, "faceId": True, "biometric": True},
    )
    assert sec.status_code == 200
