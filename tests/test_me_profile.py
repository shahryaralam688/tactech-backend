"""Personal Info / Profile Setup APIs for iOS Account Settings."""

from __future__ import annotations

import io
from uuid import uuid4

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
    return {"token": body["accessToken"], "user_id": body["user"]["id"], "role": body["user"]["role"]}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def trainer(client: TestClient) -> dict:
    settings = get_settings()
    return _login(client, "trainer@tactech.app", settings.seed_trainer_password)


@pytest.fixture(scope="module")
def trainee(client: TestClient) -> dict:
    settings = get_settings()
    return _login(client, "trainee@tactech.app", settings.seed_trainee_password)


def test_get_profile_includes_gates(client: TestClient, trainer: dict) -> None:
    resp = client.get("/me/profile", headers=_auth(trainer["token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["id"] == trainer["user_id"]
    assert "profile" in body
    assert "assessmentCompleted" in body
    assert "onboardingCompleted" in body
    assert body["trainer"] is not None
    assert body["trainee"] is None


def test_patch_profile_personal_info_and_onboarding(
    client: TestClient, trainee: dict
) -> None:
    patch = client.patch(
        "/me/profile",
        headers=_auth(trainee["token"]),
        json={
            "name": "Jordan Hale",
            "gender": "Male",
            "location": "Karachi",
            "heightCm": 178,
            "weightKg": 76.5,
            "avatarAsset": "Avatar_01_Color",
        },
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["profile"]["gender"] == "Male"
    assert body["profile"]["location"] == "Karachi"
    assert body["profile"]["heightCm"] == 178
    assert body["profile"]["weightKg"] == 76.5
    assert body["profile"]["avatarAsset"] == "Avatar_01_Color"
    assert body["profile"]["avatarUrl"] is None
    assert body["trainee"]["gender"] == "Male"
    assert body["trainee"]["location"] == "Karachi"
    assert body["onboardingCompleted"] is True

    me = client.get("/me", headers=_auth(trainee["token"]))
    assert me.status_code == 200
    assert me.json()["onboardingCompleted"] is True
    assert me.json()["user"]["name"] == "Jordan Hale"
    assert me.json()["trainee"]["weightKg"] == 76.5


def test_patch_email_conflict(client: TestClient, trainee: dict) -> None:
    resp = client.patch(
        "/me/profile",
        headers=_auth(trainee["token"]),
        json={"email": "trainer@tactech.app"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "CONFLICT"
    assert "already" in resp.json()["detail"].lower()


def test_patch_bad_gender(client: TestClient, trainee: dict) -> None:
    resp = client.patch(
        "/me/profile",
        headers=_auth(trainee["token"]),
        json={"gender": "Alien"},
    )
    assert resp.status_code == 400
    assert "Gender" in resp.json()["detail"]


def test_avatar_upload_and_delete(client: TestClient, trainer: dict) -> None:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    up = client.post(
        "/me/avatar",
        headers=_auth(trainer["token"]),
        files={"file": ("avatar.png", io.BytesIO(png), "image/png")},
    )
    assert up.status_code == 200, up.text
    first_url = up.json()["avatarUrl"]
    assert first_url
    assert first_url.startswith("http")
    assert up.json()["avatarAsset"] is None
    assert up.json().get("user") is not None
    assert "v_" in first_url  # versioned / cache-bust key

    profile = client.get("/me/profile", headers=_auth(trainer["token"]))
    assert profile.json()["profile"]["avatarUrl"] == first_url
    assert profile.json()["user"]["avatarUrl"] == first_url

    # Replace → new URL (no sticky CDN key)
    up2 = client.post(
        "/me/avatar",
        headers=_auth(trainer["token"]),
        files={"file": ("avatar2.png", io.BytesIO(png), "image/png")},
    )
    assert up2.status_code == 200, up2.text
    second_url = up2.json()["avatarUrl"]
    assert second_url != first_url

    deleted = client.delete("/me/avatar", headers=_auth(trainer["token"]))
    assert deleted.status_code == 204

    profile2 = client.get("/me/profile", headers=_auth(trainer["token"]))
    assert profile2.json()["profile"]["avatarUrl"] is None
    # Default catalog restored when custom cleared
    assert profile2.json()["profile"]["avatarAsset"] == "Avatar_01_Color"


def test_change_password(client: TestClient) -> None:
    settings = get_settings()
    # Use a throwaway signup so we don't break seed password for other tests
    email = f"pwd-{uuid4().hex[:8]}@tactech.app"
    signup = client.post(
        "/auth/signup",
        json={
            "name": "Pwd Tester",
            "email": email,
            "password": "oldPass123",
            "role": "trainee",
            "inviteCode": "TACT-MAYA",
        },
    )
    assert signup.status_code in {200, 201}, signup.text
    token = signup.json()["accessToken"]

    bad = client.post(
        "/me/password",
        headers=_auth(token),
        json={"currentPassword": "wrong", "newPassword": "newPass456"},
    )
    assert bad.status_code == 400
    assert "incorrect" in bad.json()["detail"].lower()

    ok = client.post(
        "/me/password",
        headers=_auth(token),
        json={"currentPassword": "oldPass123", "newPassword": "newPass456"},
    )
    assert ok.status_code == 204

    relogin = client.post("/auth/login", json={"email": email, "password": "newPass456"})
    assert relogin.status_code == 200
