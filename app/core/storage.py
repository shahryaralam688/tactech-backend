from __future__ import annotations

import io
import time
from pathlib import Path
from uuid import uuid4

from fastapi import Request, UploadFile

from app.core.config import Settings
from app.core.exceptions import FileTooLargeError, UnsupportedMediaError, ValidationAppError
from app.core.logging import get_logger

log = get_logger("tactech.storage")

IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/webp": ".webp",
}

VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/mov": ".mov",
}

VOICE_TYPES = {
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/mpeg": ".mp3",
}

FILE_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}

JPEG_MAGIC = (b"\xff\xd8\xff",)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
WEBP_RIFF = b"RIFF"
WEBP_WEBP = b"WEBP"


FORM3D_TYPES = {
    "model/fbx": ".fbx",
    "application/octet-stream": None,  # sniff by filename
    "model/gltf-binary": ".glb",
    "model/gltf+json": ".gltf",
}


def ensure_upload_dir(settings: Settings) -> Path:
    root = Path(settings.upload_dir)
    (root / "avatars").mkdir(parents=True, exist_ok=True)
    (root / "support").mkdir(parents=True, exist_ok=True)
    (root / "coach" / "voice").mkdir(parents=True, exist_ok=True)
    (root / "coach" / "images").mkdir(parents=True, exist_ok=True)
    (root / "chat").mkdir(parents=True, exist_ok=True)
    (root / "verify").mkdir(parents=True, exist_ok=True)
    (root / "form3d").mkdir(parents=True, exist_ok=True)
    return root


def media_cdn_base(settings: Settings) -> str:
    return (settings.media_cdn_base_url or settings.public_base_url or "").strip().rstrip("/")


def public_base(request: Request | None, settings: Settings) -> str:
    cdn = media_cdn_base(settings)
    if cdn:
        return cdn
    if request is not None:
        return str(request.base_url).rstrip("/")
    return ""


def absolute_media_url(
    request: Request | None, settings: Settings, stored: str | None
) -> str | None:
    """Always return absolute https/http URL when possible. Prefer CDN / PUBLIC_BASE_URL."""
    if not stored:
        return None
    value = stored.strip()
    if value.startswith("https://") or value.startswith("http://"):
        return value
    base = public_base(request, settings)
    if not base:
        # Last resort: relative path (staging without PUBLIC_BASE_URL)
        return value if value.startswith("/") else f"/{value}"
    path = value if value.startswith("/") else f"/{value}"
    return f"{base}{path}"


def s3_configured(settings: Settings) -> bool:
    return bool(
        (settings.media_s3_bucket or "").strip()
        and (settings.media_s3_access_key_id or "").strip()
        and (settings.media_s3_secret_access_key or "").strip()
    )


def process_avatar_image(data: bytes, extension: str) -> tuple[bytes, str]:
    """Recompress to JPEG ≤1024px square when Pillow can decode; else pass-through."""
    try:
        from PIL import Image
    except ImportError:
        return data, extension

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        # HEIC without plugin, etc. — store original
        return data, extension

    img = img.convert("RGB")
    max_side = 1024
    w, h = img.size
    if max(w, h) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue(), ".jpg"


def _avatar_object_key(settings: Settings, user_id: str, extension: str) -> str:
    """Unique per upload — cache-bust by path (never reuse prior public URL)."""
    prefix = (settings.media_s3_prefix or "avatars").strip().strip("/")
    safe_user = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in user_id)[:64]
    version = int(time.time())
    return f"{prefix}/{safe_user}/v_{version}_{uuid4().hex[:12]}{extension}"


def _s3_client(settings: Settings):
    import boto3

    kwargs: dict = {
        "aws_access_key_id": settings.media_s3_access_key_id.strip(),
        "aws_secret_access_key": settings.media_s3_secret_access_key.strip(),
        "region_name": (settings.media_s3_region or "auto").strip() or "auto",
    }
    endpoint = (settings.media_s3_endpoint_url or "").strip()
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("s3", **kwargs)


def save_avatar(
    settings: Settings,
    *,
    user_id: str,
    data: bytes,
    extension: str,
) -> str:
    """Persist avatar; return absolute CDN URL when possible, else /uploads/… relative."""
    data, extension = process_avatar_image(data, extension)
    key = _avatar_object_key(settings, user_id, extension)
    content_type = "image/jpeg" if extension.lower() in {".jpg", ".jpeg"} else f"image/{extension.lstrip('.')}"

    if s3_configured(settings):
        try:
            client = _s3_client(settings)
            client.put_object(
                Bucket=settings.media_s3_bucket.strip(),
                Key=key,
                Body=data,
                ContentType=content_type,
                CacheControl="public, max-age=31536000, immutable",
            )
            cdn = media_cdn_base(settings)
            if cdn:
                return f"{cdn}/{key}"
            # Path-style public URL via endpoint (dev)
            endpoint = (settings.media_s3_endpoint_url or "").rstrip("/")
            bucket = settings.media_s3_bucket.strip()
            if endpoint:
                return f"{endpoint}/{bucket}/{key}"
            return f"https://{bucket}.s3.amazonaws.com/{key}"
        except Exception:
            log.exception("avatar_s3_upload_failed", user_id=user_id)
            raise

    # Local disk fallback (versioned filename under uploads/)
    root = ensure_upload_dir(settings)
    # key like avatars/u/v_….jpg → uploads/avatars/...
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    relative = f"/uploads/{key}"
    base = media_cdn_base(settings)
    if base:
        return f"{base}{relative}"
    return relative


def normalize_client_media_url(settings: Settings, url: str | None) -> str | None:
    """Accept absolute HTTPS (CDN allowlist when set) or /uploads/… paths. Reject bare relatives."""
    if url is None:
        return None
    value = url.strip()
    if not value:
        return None
    if value.startswith("https://"):
        cdn = media_cdn_base(settings)
        if cdn:
            # Allow our CDN/public base or any https for staging flexibility when no allowlist host
            from urllib.parse import urlparse

            host = (urlparse(value).hostname or "").lower()
            allowed = (urlparse(cdn).hostname or "").lower()
            if allowed and host and host != allowed and not host.endswith(f".{allowed}"):
                # Still allow if PUBLIC_BASE differs from CDN
                pub = (settings.public_base_url or "").strip()
                pub_host = (urlparse(pub).hostname or "").lower() if pub else ""
                if pub_host and host == pub_host:
                    return value
                # Dev: allow ngrok / localhost when app_env development
                if (settings.app_env or "").lower() in {"development", "test", "local"}:
                    return value
                raise ValidationAppError(
                    "Image URL must be on the TacTech CDN.",
                    fields={"coverImageUrl": "host"},
                )
        return value
    if value.startswith("http://"):
        if (settings.app_env or "").lower() in {"development", "test", "local"}:
            return value
        raise ValidationAppError(
            "Image URL must use HTTPS.",
            fields={"coverImageUrl": "https"},
        )
    if value.startswith("/uploads/"):
        base = media_cdn_base(settings)
        return f"{base}{value}" if base else value
    raise ValidationAppError(
        "Image URL must be an absolute https URL.",
        fields={"coverImageUrl": "absolute"},
    )


def delete_avatar_object(settings: Settings, stored: str | None) -> None:
    """Best-effort delete prior custom avatar (local or S3)."""
    if not stored:
        return
    value = stored.strip()
    # S3 / CDN absolute
    if s3_configured(settings) and (
        value.startswith("http://") or value.startswith("https://")
    ):
        key = None
        prefix = (settings.media_s3_prefix or "avatars").strip().strip("/")
        marker = f"/{prefix}/"
        idx = value.find(marker)
        if idx >= 0:
            key = value[idx + 1 :].split("?", 1)[0]
        if key:
            try:
                _s3_client(settings).delete_object(
                    Bucket=settings.media_s3_bucket.strip(), Key=key
                )
            except Exception:
                log.warning("avatar_s3_delete_failed", key=key)
            return
    delete_stored(settings, value)


def _extension_for(content_type: str | None, filename: str | None) -> str:
    if content_type and content_type.lower().split(";")[0].strip() in IMAGE_TYPES:
        return IMAGE_TYPES[content_type.lower().split(";")[0].strip()]
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return ".jpg"
    if suffix == ".png":
        return ".png"
    if suffix in {".heic", ".heif"}:
        return ".heic"
    if suffix == ".webp":
        return ".webp"
    raise UnsupportedMediaError("Avatar must be JPEG, PNG, or HEIC.")


def _validate_image(data: bytes) -> None:
    if data.startswith(PNG_MAGIC):
        return
    if any(data.startswith(magic) for magic in JPEG_MAGIC):
        return
    if len(data) >= 12 and data.startswith(WEBP_RIFF) and data[8:12] == WEBP_WEBP:
        return
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return
    raise UnsupportedMediaError("Avatar must be JPEG, PNG, or HEIC.")


async def read_image(
    file: UploadFile,
    settings: Settings,
    *,
    max_bytes: int | None = None,
) -> tuple[bytes, str]:
    data = await file.read()
    if not data:
        raise ValidationAppError("Choose an image to upload.")
    limit = max_bytes if max_bytes is not None else settings.max_upload_bytes
    if len(data) > limit:
        raise FileTooLargeError(f"Image must be {limit // (1024 * 1024)}MB or smaller.")
    extension = _extension_for(file.content_type, file.filename)
    _validate_image(data)
    return data, extension


def _sniff_attachment_type(
    content_type: str | None,
    filename: str | None,
    hinted: str | None,
) -> str:
    if hinted in {"image", "video", "voice", "file"}:
        return hinted
    ct = (content_type or "").lower().split(";")[0].strip()
    if ct in IMAGE_TYPES or ct.startswith("image/"):
        return "image"
    if ct in VIDEO_TYPES or ct.startswith("video/"):
        return "video"
    if ct in VOICE_TYPES or ct.startswith("audio/"):
        return "voice"
    if ct in FILE_TYPES:
        return "file"
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}:
        return "image"
    if suffix in {".mp4", ".mov", ".m4v"}:
        return "video"
    if suffix in {".m4a", ".aac", ".mp3", ".caf"}:
        return "voice"
    if suffix in {".pdf", ".doc", ".docx"}:
        return "file"
    raise UnsupportedMediaError(
        "Unsupported attachment. Use JPEG/PNG/HEIC/WebP, MP4/MOV, AAC/M4A voice, or PDF."
    )


def _extension_for_chat(attachment_type: str, content_type: str | None, filename: str | None) -> str:
    ct = (content_type or "").lower().split(";")[0].strip()
    table = {
        "image": IMAGE_TYPES,
        "video": VIDEO_TYPES,
        "voice": VOICE_TYPES,
        "file": FILE_TYPES,
    }[attachment_type]
    if ct in table:
        return table[ct]
    suffix = Path(filename or "").suffix.lower()
    if attachment_type == "image":
        if suffix in {".jpg", ".jpeg"}:
            return ".jpg"
        if suffix in {".png", ".heic", ".heif", ".webp"}:
            return suffix
        return ".jpg"
    if attachment_type == "video":
        return ".mov" if suffix == ".mov" else ".mp4"
    if attachment_type == "voice":
        if suffix == ".aac":
            return ".aac"
        if suffix == ".mp3":
            return ".mp3"
        return ".m4a"
    if suffix in {".pdf", ".doc", ".docx"}:
        return suffix
    return ".bin"


def _max_bytes_for(settings: Settings, attachment_type: str) -> int:
    return {
        "image": settings.chat_image_max_bytes,
        "video": settings.chat_video_max_bytes,
        "voice": settings.chat_voice_max_bytes,
        "file": settings.chat_file_max_bytes,
    }[attachment_type]


async def read_chat_attachment(
    file: UploadFile,
    settings: Settings,
    *,
    attachment_type_hint: str | None = None,
) -> tuple[bytes, str, str]:
    """Return (bytes, extension, attachment_type)."""
    data = await file.read()
    if not data:
        raise ValidationAppError("Choose a file to upload.")
    attachment_type = _sniff_attachment_type(file.content_type, file.filename, attachment_type_hint)
    limit = _max_bytes_for(settings, attachment_type)
    if len(data) > limit:
        raise FileTooLargeError(
            f"{attachment_type.capitalize()} must be {limit // (1024 * 1024)}MB or smaller."
        )
    if attachment_type == "image":
        try:
            _validate_image(data)
        except ValidationAppError as exc:
            raise UnsupportedMediaError(str(exc.message)) from exc
    extension = _extension_for_chat(attachment_type, file.content_type, file.filename)
    return data, extension, attachment_type


def save_bytes(settings: Settings, relative_dir: str, data: bytes, extension: str) -> str:
    root = ensure_upload_dir(settings)
    filename = f"{uuid4().hex}{extension}"
    path = root / relative_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"/uploads/{relative_dir}/{filename}"


def save_form3d_asset(
    settings: Settings,
    *,
    filename: str,
    data: bytes,
    content_type: str | None,
) -> tuple[str, str, str]:
    """Persist Mixamo FBX/GLB for Form Studio. Returns (stored_url_or_path, object_key, content_type)."""
    if not data:
        raise ValidationAppError("Choose an FBX or GLB file to upload.")
    limit = 40 * 1024 * 1024
    if len(data) > limit:
        raise FileTooLargeError("Form 3D asset must be 40MB or smaller.")

    name = (filename or "clip.fbx").strip()
    lower = name.lower()
    if lower.endswith(".fbx"):
        ext = ".fbx"
        ctype = "model/fbx"
    elif lower.endswith(".glb"):
        ext = ".glb"
        ctype = "model/gltf-binary"
    elif lower.endswith(".gltf"):
        ext = ".gltf"
        ctype = "model/gltf+json"
    else:
        raise UnsupportedMediaError("Only .fbx, .glb, or .gltf Form Studio assets are allowed.")

    version = int(time.time())
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in Path(name).stem)[:80]
    key = f"form3d/x_bot/{safe}_v{version}_{uuid4().hex[:8]}{ext}"

    if s3_configured(settings):
        try:
            client = _s3_client(settings)
            client.put_object(
                Bucket=settings.media_s3_bucket.strip(),
                Key=key,
                Body=data,
                ContentType=ctype,
                CacheControl="public, max-age=31536000, immutable",
            )
            cdn = media_cdn_base(settings)
            if cdn:
                return f"{cdn}/{key}", key, ctype
            endpoint = (settings.media_s3_endpoint_url or "").rstrip("/")
            bucket = settings.media_s3_bucket.strip()
            if endpoint:
                return f"{endpoint}/{bucket}/{key}", key, ctype
            return f"https://{bucket}.s3.amazonaws.com/{key}", key, ctype
        except Exception:
            log.exception("form3d_s3_upload_failed", key=key)
            raise

    root = ensure_upload_dir(settings)
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    relative = f"/uploads/{key}"
    base = media_cdn_base(settings)
    if base:
        return f"{base}{relative}", key, ctype
    return relative, key, ctype


def delete_stored(settings: Settings, stored: str | None) -> None:
    if not stored:
        return
    relative = stored
    if relative.startswith("http://") or relative.startswith("https://"):
        marker = "/uploads/"
        index = relative.find(marker)
        if index < 0:
            return
        relative = relative[index:]
    if not relative.startswith("/uploads/"):
        return
    path = Path(settings.upload_dir) / relative.removeprefix("/uploads/")
    if path.is_file():
        path.unlink()
