"""Coach verification & trust badges (Phase 7).

Docs stored under /uploads/verify/{userId}/…  
Retention: VERIFY_DOC_RETENTION_DAYS (default 90) after approved|rejected — see docs/COACH_VERIFICATION.md.
Upload “presign” is a local PUT slot (Redis) suitable for mobile + ngrok staging.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.core.storage import ensure_upload_dir
from app.db import models
from app.repositories.coach_profile import CoachProfileRepository
from app.schemas.verification import (
    DOC_TYPES,
    VERIFY_CONTENT_TYPES,
    AdminActionOut,
    AdminApplicationOut,
    AdminApplicationPage,
    AdminRejectRequest,
    MeCoachVerificationOut,
    VerifyApplicationCreateRequest,
    VerifyApplicationOut,
    VerifyCancelOut,
    VerifyDocumentOut,
    VerifyUploadOut,
    VerifyUploadRequest,
)

if TYPE_CHECKING:
    from app.api.deps import Principal

log = get_logger("tactech.verification")

OPEN_STATUSES = frozenset({"submitted", "under_review"})
UPLOAD_PREFIX = "verify_upload"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ext_for(content_type: str, file_name: str | None) -> str:
    ct = content_type.lower().split(";")[0].strip()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "application/pdf": ".pdf",
    }
    if ct in mapping:
        return mapping[ct]
    suffix = Path(file_name or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".bin"


class VerificationService:
    def __init__(self, db: Session, settings: Settings, redis_client: Redis) -> None:
        self.db = db
        self.settings = settings
        self.redis = redis_client
        self.profiles = CoachProfileRepository(db)

    def _require_profile(self, principal: Principal) -> models.CoachProfile:
        if principal.role != "trainer" or not principal.trainer_id:
            raise ForbiddenError("Trainer access required.")
        profile = self.profiles.get_by_trainer_id(principal.trainer_id)
        if profile is None:
            raise NotFoundError("Coach profile not found. Create your coach profile first.")
        return profile

    # --- Uploads -----------------------------------------------------------

    def create_upload_slot(
        self, principal: Principal, payload: VerifyUploadRequest, *, public_base: str
    ) -> VerifyUploadOut:
        self._require_profile(principal)
        doc_type = (payload.doc_type or "").strip().lower()
        if doc_type not in DOC_TYPES:
            raise ValidationAppError(
                "docType must be government_id, certification, selfie, or other.",
                fields={"docType": "invalid"},
            )
        content_type = (payload.content_type or "").lower().split(";")[0].strip()
        if content_type not in VERIFY_CONTENT_TYPES:
            raise ValidationAppError(
                "Unsupported contentType. Use JPEG/PNG/WebP/HEIC or PDF.",
                fields={"contentType": "invalid"},
            )
        upload_id = str(uuid4())
        ext = _ext_for(content_type, payload.file_name)
        file_key = f"verify/{principal.user_id}/{upload_id}{ext}"
        file_url = f"/uploads/{file_key}"
        expires = _utcnow() + timedelta(seconds=int(self.settings.verify_upload_ttl_seconds))
        slot = {
            "uploadId": upload_id,
            "userId": principal.user_id,
            "docType": doc_type,
            "contentType": content_type,
            "fileKey": file_key,
            "fileUrl": file_url,
            "fileName": payload.file_name or "",
            "expiresAt": expires.isoformat(),
            "received": False,
        }
        self.redis.setex(
            f"{UPLOAD_PREFIX}:{upload_id}",
            int(self.settings.verify_upload_ttl_seconds),
            json.dumps(slot),
        )
        upload_url = f"{public_base.rstrip('/')}/me/coach-verification/uploads/{upload_id}"
        return VerifyUploadOut(
            upload_id=upload_id,
            doc_type=doc_type,
            upload_url=upload_url,
            file_key=file_key,
            file_url=file_url,
            expires_at=expires,
        )

    def put_upload_bytes(self, principal: Principal, upload_id: str, data: bytes) -> dict:
        raw = self.redis.get(f"{UPLOAD_PREFIX}:{upload_id}")
        if not raw:
            raise NotFoundError("Upload slot expired or not found.")
        slot = json.loads(raw)
        if slot.get("userId") != principal.user_id:
            raise ForbiddenError("This upload does not belong to you.")
        if not data:
            raise ValidationAppError("Empty file.", fields={"file": "empty"})
        if len(data) > int(self.settings.verify_upload_max_bytes):
            raise ValidationAppError(
                f"File must be {self.settings.verify_upload_max_bytes // (1024 * 1024)}MB or smaller.",
                fields={"file": "too_large"},
            )
        ensure_upload_dir(self.settings)
        rel = slot["fileKey"]  # verify/user/id.ext
        path = Path(self.settings.upload_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        slot["received"] = True
        ttl = self.redis.ttl(f"{UPLOAD_PREFIX}:{upload_id}")
        self.redis.setex(
            f"{UPLOAD_PREFIX}:{upload_id}",
            ttl if ttl and ttl > 0 else int(self.settings.verify_upload_ttl_seconds),
            json.dumps(slot),
        )
        log.info("verify_upload_received", upload_id=upload_id, user_id=principal.user_id)
        return {"ok": True, "fileKey": slot["fileKey"], "fileUrl": slot["fileUrl"]}

    def _assert_file_key_owned(self, user_id: str, file_key: str) -> tuple[str, str]:
        """Return (file_key, file_url). File must exist under verify/{userId}/."""
        key = (file_key or "").strip().lstrip("/")
        if key.startswith("uploads/"):
            key = key.removeprefix("uploads/")
        prefix = f"verify/{user_id}/"
        if not key.startswith(prefix):
            raise ValidationAppError(
                "Invalid fileKey for this account.",
                fields={"fileKey": "invalid"},
            )
        path = Path(self.settings.upload_dir) / key
        if not path.is_file():
            raise ValidationAppError(
                "Document file not found. Upload again, then submit.",
                fields={"fileKey": "missing"},
            )
        return key, f"/uploads/{key}"

    # --- Trainer -----------------------------------------------------------

    def get_me(self, principal: Principal) -> MeCoachVerificationOut:
        profile = self._require_profile(principal)
        app = self._latest_application(principal.user_id)
        return MeCoachVerificationOut(
            is_verified=bool(profile.is_verified),
            verification_status=profile.verification_status or "none",
            verified_at=profile.verified_at,
            application=self._app_out(app, include_download=True) if app else None,
        )

    def submit(
        self, principal: Principal, payload: VerifyApplicationCreateRequest
    ) -> VerifyApplicationOut:
        profile = self._require_profile(principal)
        if profile.is_verified:
            raise ConflictError(
                "Your coach profile is already verified.",
                fields={"verification": "already_verified"},
            )
        open_app = self._open_application(principal.user_id)
        if open_app is not None:
            raise ConflictError(
                "You already have a verification application in progress.",
                fields={"application": "open"},
            )
        if not payload.attestation_accepted:
            raise ValidationAppError(
                "You must accept the attestation to submit.",
                fields={"attestationAccepted": "required"},
            )
        legal = (payload.legal_full_name or "").strip()
        if not legal:
            raise ValidationAppError(
                "Legal full name is required.",
                fields={"legalFullName": "required"},
            )
        country = (payload.country_code or "PK").strip().upper()
        if len(country) != 2:
            raise ValidationAppError(
                "countryCode must be 2 letters.",
                fields={"countryCode": "invalid"},
            )
        docs = payload.documents or []
        types = {(d.doc_type or "").strip().lower() for d in docs}
        if "government_id" not in types:
            raise ValidationAppError(
                "At least one government ID document is required.",
                fields={"documents": "government_id_required"},
            )
        if "certification" not in types:
            raise ValidationAppError(
                "At least one certification document is required.",
                fields={"documents": "certification_required"},
            )

        now = _utcnow()
        app = models.CoachVerificationApplication(
            id=str(uuid4()),
            coach_profile_id=profile.id,
            trainer_id=profile.trainer_id,
            user_id=principal.user_id,
            status="submitted",
            legal_full_name=legal,
            country_code=country,
            phone_last4=(payload.phone_last4 or "").strip() or None,
            attestation_accepted=True,
            attestation_accepted_at=now,
            rejection_reason=None,
            submitted_at=now,
            created_at=now,
            updated_at=now,
        )
        self.db.add(app)
        self.db.flush()

        for d in docs:
            dtype = (d.doc_type or "").strip().lower()
            if dtype not in DOC_TYPES:
                raise ValidationAppError(
                    f"Invalid docType: {d.doc_type}",
                    fields={"documents": "invalid_doc_type"},
                )
            ct = (d.content_type or "").lower().split(";")[0].strip()
            if ct not in VERIFY_CONTENT_TYPES:
                raise ValidationAppError(
                    "Unsupported document contentType.",
                    fields={"documents": "invalid_content_type"},
                )
            file_key, file_url = self._assert_file_key_owned(principal.user_id, d.file_key)
            self.db.add(
                models.CoachVerificationDocument(
                    id=str(uuid4()),
                    application_id=app.id,
                    doc_type=dtype,
                    file_url=file_url,
                    file_key=file_key,
                    content_type=ct,
                    original_file_name=(d.original_file_name or "").strip() or None,
                    created_at=now,
                )
            )

        profile.verification_status = "pending"
        profile.updated_at = now
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(app)
        log.info(
            "verify_submitted",
            application_id=app.id,
            coach_profile_id=profile.id,
            user_id=principal.user_id,
        )
        return self._app_out(app, include_download=True)

    def cancel(self, principal: Principal) -> VerifyCancelOut:
        profile = self._require_profile(principal)
        app = self._open_application(principal.user_id)
        if app is None or app.status != "submitted":
            raise ValidationAppError(
                "No cancelable submitted application.",
                fields={"application": "not_cancelable"},
            )
        now = _utcnow()
        app.status = "canceled"
        app.updated_at = now
        self.db.add(app)
        if not profile.is_verified:
            profile.verification_status = "none"
            profile.updated_at = now
            self.db.add(profile)
        self.db.commit()
        log.info("verify_canceled", application_id=app.id, user_id=principal.user_id)
        return VerifyCancelOut(
            canceled=True,
            verification_status=profile.verification_status or "none",
        )

    # --- Admin -------------------------------------------------------------

    def admin_list(
        self, *, status: str | None = "submitted", limit: int = 50
    ) -> AdminApplicationPage:
        limit = max(1, min(limit, 100))
        stmt = select(models.CoachVerificationApplication).order_by(
            models.CoachVerificationApplication.submitted_at.desc().nullslast(),
            models.CoachVerificationApplication.created_at.desc(),
        )
        if status:
            stmt = stmt.where(models.CoachVerificationApplication.status == status)
        rows = list(self.db.scalars(stmt.limit(limit)).all())
        items: list[AdminApplicationOut] = []
        for app in rows:
            user = self.db.get(models.User, app.user_id)
            profile = self.db.get(models.CoachProfile, app.coach_profile_id)
            docs = self._docs_for(app.id)
            items.append(
                AdminApplicationOut(
                    id=app.id,
                    status=app.status,
                    coach_profile_id=app.coach_profile_id,
                    trainer_id=app.trainer_id,
                    user_id=app.user_id,
                    trainer_name=user.name if user else "",
                    city=profile.city if profile else None,
                    legal_full_name=app.legal_full_name,
                    country_code=app.country_code,
                    submitted_at=app.submitted_at,
                    document_count=len(docs),
                    documents=[
                        VerifyDocumentOut(
                            id=d.id,
                            doc_type=d.doc_type,
                            content_type=d.content_type,
                            original_file_name=d.original_file_name,
                            created_at=d.created_at,
                            download_url=self._public_file_url(d.file_url),
                        )
                        for d in docs
                    ],
                )
            )
        return AdminApplicationPage(items=items)

    def admin_approve(self, application_id: str, *, reviewer_label: str) -> AdminActionOut:
        app = self.db.get(models.CoachVerificationApplication, application_id)
        if app is None:
            raise NotFoundError("Application not found.")
        if app.status not in OPEN_STATUSES:
            raise ValidationAppError(
                "Only submitted/under_review applications can be approved.",
                fields={"status": "invalid"},
            )
        profile = self.db.get(models.CoachProfile, app.coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach profile not found.")
        now = _utcnow()
        app.status = "approved"
        app.reviewed_at = now
        app.reviewer_user_id = reviewer_label
        app.rejection_reason = None
        app.updated_at = now
        profile.is_verified = True
        profile.verified_at = now
        profile.verification_status = "approved"
        profile.updated_at = now
        self.db.add(app)
        self.db.add(profile)
        self.db.commit()
        log.info(
            "verify_approved",
            application_id=app.id,
            coach_profile_id=profile.id,
            reviewer=reviewer_label,
        )
        return AdminActionOut(
            ok=True,
            is_verified=True,
            verification_status="approved",
            application_id=app.id,
        )

    def admin_reject(
        self, application_id: str, payload: AdminRejectRequest, *, reviewer_label: str
    ) -> AdminActionOut:
        app = self.db.get(models.CoachVerificationApplication, application_id)
        if app is None:
            raise NotFoundError("Application not found.")
        if app.status not in OPEN_STATUSES:
            raise ValidationAppError(
                "Only submitted/under_review applications can be rejected.",
                fields={"status": "invalid"},
            )
        reason = (payload.reason or "").strip()
        if not reason:
            raise ValidationAppError("Rejection reason is required.", fields={"reason": "required"})
        profile = self.db.get(models.CoachProfile, app.coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach profile not found.")
        now = _utcnow()
        app.status = "rejected"
        app.rejection_reason = reason[:500]
        app.reviewed_at = now
        app.reviewer_user_id = reviewer_label
        app.updated_at = now
        profile.is_verified = False
        profile.verified_at = None
        profile.verification_status = "rejected"
        profile.updated_at = now
        self.db.add(app)
        self.db.add(profile)
        self.db.commit()
        log.info(
            "verify_rejected",
            application_id=app.id,
            coach_profile_id=profile.id,
            reviewer=reviewer_label,
        )
        return AdminActionOut(
            ok=True,
            is_verified=False,
            verification_status="rejected",
            application_id=app.id,
        )

    def admin_revoke(self, coach_profile_id: str, *, reviewer_label: str) -> AdminActionOut:
        profile = self.db.get(models.CoachProfile, coach_profile_id)
        if profile is None:
            raise NotFoundError("Coach profile not found.")
        now = _utcnow()
        profile.is_verified = False
        profile.verified_at = None
        profile.verification_status = "revoked"
        profile.updated_at = now
        self.db.add(profile)
        self.db.commit()
        log.info(
            "verify_revoked",
            coach_profile_id=profile.id,
            reviewer=reviewer_label,
        )
        return AdminActionOut(
            ok=True,
            is_verified=False,
            verification_status="revoked",
            application_id=None,
        )

    # --- helpers -----------------------------------------------------------

    def _latest_application(self, user_id: str) -> models.CoachVerificationApplication | None:
        return self.db.scalars(
            select(models.CoachVerificationApplication)
            .where(models.CoachVerificationApplication.user_id == user_id)
            .order_by(models.CoachVerificationApplication.created_at.desc())
        ).first()

    def _open_application(self, user_id: str) -> models.CoachVerificationApplication | None:
        return self.db.scalars(
            select(models.CoachVerificationApplication).where(
                models.CoachVerificationApplication.user_id == user_id,
                models.CoachVerificationApplication.status.in_(tuple(OPEN_STATUSES)),
            )
        ).first()

    def _docs_for(self, application_id: str) -> list[models.CoachVerificationDocument]:
        return list(
            self.db.scalars(
                select(models.CoachVerificationDocument)
                .where(models.CoachVerificationDocument.application_id == application_id)
                .order_by(models.CoachVerificationDocument.created_at.asc())
            ).all()
        )

    def _public_file_url(self, file_url: str) -> str:
        base = (self.settings.public_base_url or "").rstrip("/")
        if file_url.startswith("http"):
            return file_url
        if base:
            return f"{base}{file_url if file_url.startswith('/') else '/' + file_url}"
        return file_url

    def _app_out(
        self, app: models.CoachVerificationApplication, *, include_download: bool
    ) -> VerifyApplicationOut:
        docs = self._docs_for(app.id)
        return VerifyApplicationOut(
            id=app.id,
            status=app.status,
            legal_full_name=app.legal_full_name,
            country_code=app.country_code,
            attestation_accepted=app.attestation_accepted,
            rejection_reason=app.rejection_reason,
            submitted_at=app.submitted_at,
            reviewed_at=app.reviewed_at,
            documents=[
                VerifyDocumentOut(
                    id=d.id,
                    doc_type=d.doc_type,
                    content_type=d.content_type,
                    original_file_name=d.original_file_name,
                    created_at=d.created_at,
                    download_url=self._public_file_url(d.file_url) if include_download else None,
                )
                for d in docs
            ],
        )
