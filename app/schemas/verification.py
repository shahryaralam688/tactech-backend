"""Coach verification DTOs (Phase 7)."""

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel

DOC_TYPES = frozenset({"government_id", "certification", "selfie", "other"})
VERIFY_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
        "application/pdf",
    }
)


class VerifyUploadRequest(APIModel):
    doc_type: str = Field(max_length=32)
    content_type: str = Field(max_length=128)
    file_name: str | None = Field(default=None, max_length=255)


class VerifyUploadOut(APIModel):
    upload_id: str
    doc_type: str
    upload_url: str
    file_key: str
    file_url: str
    expires_at: datetime


class VerifyDocIn(APIModel):
    doc_type: str = Field(max_length=32)
    file_key: str = Field(min_length=1, max_length=512)
    content_type: str = Field(max_length=128)
    original_file_name: str | None = Field(default=None, max_length=255)
    file_url: str | None = Field(default=None, max_length=1024)


class VerifyApplicationCreateRequest(APIModel):
    legal_full_name: str = Field(min_length=1, max_length=255)
    country_code: str = Field(default="PK", min_length=2, max_length=2)
    phone_last4: str | None = Field(default=None, max_length=4)
    attestation_accepted: bool
    documents: list[VerifyDocIn] = Field(default_factory=list, max_length=10)


class VerifyDocumentOut(APIModel):
    id: str
    doc_type: str
    content_type: str
    original_file_name: str | None = None
    created_at: datetime
    # Owner/admin only — omitted on public discovery
    download_url: str | None = None


class VerifyApplicationOut(APIModel):
    id: str
    status: str
    legal_full_name: str
    country_code: str
    attestation_accepted: bool
    rejection_reason: str | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    documents: list[VerifyDocumentOut] = Field(default_factory=list)


class MeCoachVerificationOut(APIModel):
    is_verified: bool = False
    verification_status: str = "none"
    verified_at: datetime | None = None
    application: VerifyApplicationOut | None = None


class VerifyCancelOut(APIModel):
    canceled: bool = True
    verification_status: str = "none"


class AdminRejectRequest(APIModel):
    reason: str = Field(min_length=1, max_length=500)


class AdminApplicationOut(APIModel):
    id: str
    status: str
    coach_profile_id: str
    trainer_id: str
    user_id: str
    trainer_name: str
    city: str | None = None
    legal_full_name: str
    country_code: str
    submitted_at: datetime | None = None
    document_count: int = 0
    documents: list[VerifyDocumentOut] = Field(default_factory=list)


class AdminApplicationPage(APIModel):
    items: list[AdminApplicationOut] = Field(default_factory=list)


class AdminActionOut(APIModel):
    ok: bool = True
    is_verified: bool = False
    verification_status: str
    application_id: str | None = None
