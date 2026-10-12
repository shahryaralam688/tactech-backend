"""Phase 7 — coach verification & trust badges."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
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
    return {
        "trainer": _login(client, "trainer@tactech.app", settings.seed_trainer_password),
        "ali": _login(client, "ali.coach@tactech.app", settings.seed_trainer_password),
        "sara": _login(client, "sara.coach@tactech.app", settings.seed_trainer_password),
        "trainee": _login(client, "trainee@tactech.app", settings.seed_trainee_password),
        "admin_key": (settings.admin_api_key or "").strip() or "test-admin-key",
    }


@pytest.fixture(autouse=True)
def _ensure_admin_key(users: dict) -> None:
    settings = get_settings()
    if not (settings.admin_api_key or "").strip():
        object.__setattr__(settings, "admin_api_key", users["admin_key"])
    users["admin_key"] = settings.admin_api_key


def _admin_headers(users: dict) -> dict[str, str]:
    return {"X-Admin-Key": users["admin_key"]}


def _clear_open_apps(user_id: str) -> None:
    from sqlalchemy import select

    db = SessionLocal()
    try:
        apps = db.scalars(
            select(models.CoachVerificationApplication).where(
                models.CoachVerificationApplication.user_id == user_id,
                models.CoachVerificationApplication.status.in_(
                    ("submitted", "under_review", "draft")
                ),
            )
        ).all()
        for app in apps:
            for d in db.scalars(
                select(models.CoachVerificationDocument).where(
                    models.CoachVerificationDocument.application_id == app.id
                )
            ).all():
                db.delete(d)
            db.delete(app)
        profile = db.scalars(
            select(models.CoachProfile).where(models.CoachProfile.user_id == user_id)
        ).first()
        if profile and not profile.is_verified:
            profile.verification_status = "none"
        db.commit()
    finally:
        db.close()


def _upload_doc(client: TestClient, token: str, doc_type: str, name: str) -> dict:
    slot = client.post(
        "/me/coach-verification/uploads",
        headers=_auth(token),
        json={
            "docType": doc_type,
            "contentType": "image/jpeg",
            "fileName": name,
        },
    )
    assert slot.status_code == 200, slot.text
    body = slot.json()
    # Minimal JPEG
    jpeg = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xd9"
    )
    put = client.put(
        f"/me/coach-verification/uploads/{body['uploadId']}",
        headers=_auth(token),
        content=jpeg,
    )
    assert put.status_code == 200, put.text
    return body


def test_submit_requires_cert(client: TestClient, users: dict) -> None:
    _clear_open_apps(users["sara"]["user_id"])
    # Ensure not verified
    db = SessionLocal()
    try:
        p = db.get(models.CoachProfile, "cp-sara")
        assert p
        p.is_verified = False
        p.verification_status = "none"
        db.commit()
    finally:
        db.close()

    gov = _upload_doc(client, users["sara"]["token"], "government_id", "id.jpg")
    res = client.post(
        "/me/coach-verification/applications",
        headers=_auth(users["sara"]["token"]),
        json={
            "legalFullName": "Sara Ahmed",
            "countryCode": "PK",
            "attestationAccepted": True,
            "documents": [
                {
                    "docType": "government_id",
                    "fileKey": gov["fileKey"],
                    "contentType": "image/jpeg",
                    "originalFileName": "id.jpg",
                }
            ],
        },
    )
    assert res.status_code == 400, res.text


def test_submit_and_admin_approve(client: TestClient, users: dict) -> None:
    _clear_open_apps(users["sara"]["user_id"])
    db = SessionLocal()
    try:
        p = db.get(models.CoachProfile, "cp-sara")
        assert p
        p.is_verified = False
        p.verified_at = None
        p.verification_status = "none"
        db.commit()
    finally:
        db.close()

    gov = _upload_doc(client, users["sara"]["token"], "government_id", "cnic.jpg")
    cert = _upload_doc(client, users["sara"]["token"], "certification", "cert.jpg")
    created = client.post(
        "/me/coach-verification/applications",
        headers=_auth(users["sara"]["token"]),
        json={
            "legalFullName": "Sara Ahmed",
            "countryCode": "PK",
            "attestationAccepted": True,
            "documents": [
                {
                    "docType": "government_id",
                    "fileKey": gov["fileKey"],
                    "contentType": "image/jpeg",
                    "originalFileName": "cnic.jpg",
                },
                {
                    "docType": "certification",
                    "fileKey": cert["fileKey"],
                    "contentType": "image/jpeg",
                    "originalFileName": "cert.jpg",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]
    assert created.json()["status"] == "submitted"

    me = client.get("/me/coach-verification", headers=_auth(users["sara"]["token"]))
    assert me.status_code == 200
    assert me.json()["verificationStatus"] == "pending"
    assert me.json()["application"]["id"] == app_id

    # Second submit while pending → 409
    again = client.post(
        "/me/coach-verification/applications",
        headers=_auth(users["sara"]["token"]),
        json={
            "legalFullName": "Sara Ahmed",
            "countryCode": "PK",
            "attestationAccepted": True,
            "documents": [
                {
                    "docType": "government_id",
                    "fileKey": gov["fileKey"],
                    "contentType": "image/jpeg",
                },
                {
                    "docType": "certification",
                    "fileKey": cert["fileKey"],
                    "contentType": "image/jpeg",
                },
            ],
        },
    )
    assert again.status_code == 409

    approve = client.post(
        f"/admin/coach-verification/applications/{app_id}/approve",
        headers=_admin_headers(users),
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["isVerified"] is True

    detail = client.get("/coaches/cp-sara", headers=_auth(users["trainee"]["token"]))
    assert detail.status_code == 200
    assert detail.json()["isVerified"] is True
    assert detail.json()["verifiedBadge"] == "Verified Coach"
    assert "fileUrl" not in detail.json()
    assert "documents" not in detail.json()

    # Already verified → 409
    conflict = client.post(
        "/me/coach-verification/applications",
        headers=_auth(users["sara"]["token"]),
        json={
            "legalFullName": "Sara Ahmed",
            "countryCode": "PK",
            "attestationAccepted": True,
            "documents": [
                {
                    "docType": "government_id",
                    "fileKey": gov["fileKey"],
                    "contentType": "image/jpeg",
                },
                {
                    "docType": "certification",
                    "fileKey": cert["fileKey"],
                    "contentType": "image/jpeg",
                },
            ],
        },
    )
    assert conflict.status_code == 409


def test_admin_reject_reason_on_me(client: TestClient, users: dict) -> None:
    _clear_open_apps(users["ali"]["user_id"])
    db = SessionLocal()
    try:
        p = db.get(models.CoachProfile, "cp-ali")
        assert p
        p.is_verified = False
        p.verification_status = "none"
        db.commit()
    finally:
        db.close()

    gov = _upload_doc(client, users["ali"]["token"], "government_id", "id.jpg")
    cert = _upload_doc(client, users["ali"]["token"], "certification", "cert.jpg")
    created = client.post(
        "/me/coach-verification/applications",
        headers=_auth(users["ali"]["token"]),
        json={
            "legalFullName": "Ali Khan",
            "countryCode": "PK",
            "attestationAccepted": True,
            "documents": [
                {
                    "docType": "government_id",
                    "fileKey": gov["fileKey"],
                    "contentType": "image/jpeg",
                },
                {
                    "docType": "certification",
                    "fileKey": cert["fileKey"],
                    "contentType": "image/jpeg",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]

    reject = client.post(
        f"/admin/coach-verification/applications/{app_id}/reject",
        headers=_admin_headers(users),
        json={"reason": "Certification unreadable. Please re-upload a clearer PDF."},
    )
    assert reject.status_code == 200, reject.text

    me = client.get("/me/coach-verification", headers=_auth(users["ali"]["token"]))
    assert me.status_code == 200
    assert me.json()["isVerified"] is False
    assert me.json()["verificationStatus"] == "rejected"
    assert "unreadable" in (me.json()["application"]["rejectionReason"] or "")

    public = client.get("/coaches/cp-ali", headers=_auth(users["trainee"]["token"]))
    assert public.json()["isVerified"] is False
    assert "rejectionReason" not in public.json()


def test_cancel_submitted(client: TestClient, users: dict) -> None:
    # Use Omar for cancel flow
    settings = get_settings()
    omar = _login(client, "omar.coach@tactech.app", settings.seed_trainer_password)
    _clear_open_apps(omar["user_id"])
    db = SessionLocal()
    try:
        p = db.get(models.CoachProfile, "cp-omar")
        assert p
        p.is_verified = False
        p.verification_status = "none"
        db.commit()
    finally:
        db.close()

    gov = _upload_doc(client, omar["token"], "government_id", "id.jpg")
    cert = _upload_doc(client, omar["token"], "certification", "cert.jpg")
    created = client.post(
        "/me/coach-verification/applications",
        headers=_auth(omar["token"]),
        json={
            "legalFullName": "Omar Raza",
            "countryCode": "PK",
            "attestationAccepted": True,
            "documents": [
                {
                    "docType": "government_id",
                    "fileKey": gov["fileKey"],
                    "contentType": "image/jpeg",
                },
                {
                    "docType": "certification",
                    "fileKey": cert["fileKey"],
                    "contentType": "image/jpeg",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    cancel = client.post(
        "/me/coach-verification/cancel",
        headers=_auth(omar["token"]),
    )
    assert cancel.status_code == 200
    assert cancel.json()["canceled"] is True
    me = client.get("/me/coach-verification", headers=_auth(omar["token"]))
    assert me.json()["verificationStatus"] == "none"


def test_maya_seed_verified_on_list(client: TestClient, users: dict) -> None:
    res = client.get("/coaches", headers=_auth(users["trainee"]["token"]))
    assert res.status_code == 200
    maya = next(i for i in res.json()["items"] if i["id"] == "cp-maya")
    assert maya["isVerified"] is True
    # Public payload must not leak doc URLs
    blob = res.text
    assert "/uploads/verify/" not in blob


def test_admin_key_required(client: TestClient) -> None:
    res = client.get("/admin/coach-verification/applications")
    assert res.status_code == 403


def test_reviews_still_ok(client: TestClient, users: dict) -> None:
    res = client.get("/coaches/cp-maya/reviews", headers=_auth(users["trainee"]["token"]))
    assert res.status_code == 200
