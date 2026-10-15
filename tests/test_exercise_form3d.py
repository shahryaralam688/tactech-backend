"""Exercise catalog Form Studio 3D metadata."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["accessToken"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def trainee_token(client: TestClient) -> str:
    settings = get_settings()
    return _login(client, "trainee@tactech.app", settings.seed_trainee_password)


def test_list_exercises_includes_form3d(client: TestClient, trainee_token: str) -> None:
    res = client.get("/exercises", headers=_auth(trainee_token))
    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) >= 24
    ids = {e["id"] for e in items}
    for required in (
        "ex-squat",
        "ex-pushup",
        "ex-plank",
        "ex-lunge",
        "ex-rdl",
        "ex-hiphinge",
        "ex-ai-zone-2-b",
    ):
        assert required in ids

    for e in items:
        assert "form3d" in e
        assert "enabled" in e["form3d"]
        assert isinstance(e["form3d"]["enabled"], bool)
        # legacy fields intact
        assert "muscleGroup" in e
        assert "equipment" in e
        assert isinstance(e["equipment"], str)

    push = next(e for e in items if e["id"] == "ex-pushup")
    assert push["form3d"]["enabled"] is True
    assert push["form3d"]["clipId"] == "push_up"
    assert push["form3d"]["character"] == "x_bot"
    assert push["form3d"]["attribution"] == "Mixamo"

    bike = next(e for e in items if e["id"] == "ex-hiit")
    assert bike["form3d"]["enabled"] is False
    assert bike["form3d"]["clipId"] is None


def test_get_exercise_detail(client: TestClient, trainee_token: str) -> None:
    res = client.get("/exercises/ex-plank", headers=_auth(trainee_token))
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "ex-plank"
    assert body["form3d"]["enabled"] is True
    assert body["form3d"]["clipId"] == "plank"
    assert isinstance(body.get("muscles"), list)


def test_admin_form3d_update(client: TestClient) -> None:
    settings = get_settings()
    key = (settings.admin_api_key or "").strip()
    if not key:
        pytest.skip("ADMIN_API_KEY not configured")

    res = client.put(
        "/admin/exercises/ex-ohp/form3d",
        headers={"X-Admin-Key": key},
        json={
            "enabled": True,
            "clipId": "shoulder_press",
            "character": "x_bot",
            "animationUrl": None,
            "cues": ["Glutes tight"],
            "guide": [
                {
                    "focus": "Press",
                    "title": "Drive up",
                    "detail": "Press without flaring ribs.",
                    "t": 0.2,
                }
            ],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["form3d"]["enabled"] is True
    assert body["form3d"]["clipId"] == "shoulder_press"

    # restore soft (leave enabled with clip — fine for staging)


def test_admin_requires_key(client: TestClient) -> None:
    res = client.put(
        "/admin/exercises/ex-pushup/form3d",
        json={"enabled": False},
    )
    assert res.status_code in (401, 403)
