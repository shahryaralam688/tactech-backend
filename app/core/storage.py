from pathlib import Path
from uuid import uuid4

from fastapi import Request, UploadFile

from app.core.config import Settings
from app.core.exceptions import FileTooLargeError, ValidationAppError

IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
}

JPEG_MAGIC = (b"\xff\xd8\xff",)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def ensure_upload_dir(settings: Settings) -> Path:
    root = Path(settings.upload_dir)
    (root / "avatars").mkdir(parents=True, exist_ok=True)
    (root / "support").mkdir(parents=True, exist_ok=True)
    (root / "coach" / "voice").mkdir(parents=True, exist_ok=True)
    (root / "coach" / "images").mkdir(parents=True, exist_ok=True)
    return root


def public_base(request: Request, settings: Settings) -> str:
    if settings.public_base_url.strip():
        return settings.public_base_url.strip().rstrip("/")
    return str(request.base_url).rstrip("/")


def absolute_media_url(request: Request, settings: Settings, stored: str | None) -> str | None:
    if not stored:
        return None
    if stored.startswith("http://") or stored.startswith("https://"):
        return stored
    return f"{public_base(request, settings)}{stored if stored.startswith('/') else '/' + stored}"


def _extension_for(content_type: str | None, filename: str | None) -> str:
    if content_type and content_type.lower() in IMAGE_TYPES:
        return IMAGE_TYPES[content_type.lower()]
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return ".jpg"
    if suffix == ".png":
        return ".png"
    raise ValidationAppError("Upload a JPEG or PNG image.")


def _validate_image(data: bytes) -> None:
    if data.startswith(PNG_MAGIC):
        return
    if any(data.startswith(magic) for magic in JPEG_MAGIC):
        return
    raise ValidationAppError("Upload a JPEG or PNG image.")


async def read_image(file: UploadFile, settings: Settings) -> tuple[bytes, str]:
    data = await file.read()
    if not data:
        raise ValidationAppError("Choose an image to upload.")
    if len(data) > settings.max_upload_bytes:
        raise FileTooLargeError("Image must be 5MB or smaller.")
    extension = _extension_for(file.content_type, file.filename)
    _validate_image(data)
    return data, extension


def save_bytes(settings: Settings, relative_dir: str, data: bytes, extension: str) -> str:
    root = ensure_upload_dir(settings)
    filename = f"{uuid4().hex}{extension}"
    path = root / relative_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"/uploads/{relative_dir}/{filename}"


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
