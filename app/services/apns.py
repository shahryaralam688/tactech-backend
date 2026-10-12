"""Apple Push Notification service (HTTP/2 token auth). Best-effort; never raises to callers."""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger("tactech.apns")

_warned_unconfigured = False
_cached_jwt: tuple[str, float] | None = None  # (token, exp_epoch)


def apns_configured(settings: Settings) -> bool:
    key_id = (settings.apns_key_id or "").strip()
    team_id = (settings.apns_team_id or "").strip()
    pem = (settings.apns_private_key_p8 or "").strip()
    bundle = (settings.apns_bundle_id or settings.apple_bundle_id or "").strip()
    return bool(key_id and team_id and pem and bundle)


def _bundle_id(settings: Settings) -> str:
    return (settings.apns_bundle_id or settings.apple_bundle_id or "").strip()


def _host(settings: Settings) -> str:
    env = (settings.apns_environment or "sandbox").strip().lower()
    if env in {"production", "prod", "api.push.apple.com"}:
        return "api.push.apple.com"
    return "api.sandbox.push.apple.com"


def _normalize_pem(raw: str) -> str:
    text = raw.strip()
    if "\\n" in text and "-----BEGIN" in text:
        text = text.replace("\\n", "\n")
    return text


def _bearer_jwt(settings: Settings) -> str | None:
    global _cached_jwt
    now = time.time()
    if _cached_jwt and _cached_jwt[1] > now + 60:
        return _cached_jwt[0]
    try:
        pem = _normalize_pem(settings.apns_private_key_p8)
        token = jwt.encode(
            {"iss": settings.apns_team_id.strip(), "iat": int(now)},
            pem,
            algorithm="ES256",
            headers={"alg": "ES256", "kid": settings.apns_key_id.strip()},
        )
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        _cached_jwt = (token, now + 50 * 60)
        return token
    except Exception:
        log.exception("apns_jwt_failed")
        return None


async def send_alert(
    settings: Settings,
    *,
    device_token: str,
    title: str,
    body: str,
    badge: int,
    data: dict[str, str] | None = None,
    high_priority: bool = False,
) -> str | None:
    """Send one APNs alert. Returns None on success, or reason string on failure."""
    global _warned_unconfigured
    if not apns_configured(settings):
        if not _warned_unconfigured:
            _warned_unconfigured = True
            log.warning(
                "apns_not_configured",
                hint="Set APNS_KEY_ID, APNS_TEAM_ID, APNS_BUNDLE_ID, APNS_PRIVATE_KEY_P8",
            )
        return "not_configured"

    bearer = _bearer_jwt(settings)
    if not bearer:
        return "jwt_failed"

    token = device_token.strip()
    if not token:
        return "empty_token"

    payload: dict[str, Any] = {
        "aps": {
            "alert": {"title": title[:100], "body": body[:200]},
            "badge": max(0, int(badge)),
            "sound": "default",
        }
    }
    for key, value in (data or {}).items():
        if key == "aps":
            continue
        payload[key] = value

    url = f"https://{_host(settings)}/3/device/{token}"
    headers = {
        "authorization": f"bearer {bearer}",
        "apns-topic": _bundle_id(settings),
        "apns-push-type": "alert",
        "apns-priority": "10" if high_priority else "5",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(http2=True, timeout=12.0) as client:
            res = await client.post(url, headers=headers, json=payload)
    except Exception as exc:
        log.warning("apns_http_failed", error=str(exc)[:200])
        return "http_error"

    if res.status_code == 200:
        return None

    reason = "unknown"
    try:
        reason = str((res.json() or {}).get("reason") or res.text)[:120]
    except Exception:
        reason = (res.text or str(res.status_code))[:120]
    log.warning(
        "apns_rejected",
        status=res.status_code,
        reason=reason,
        token_suffix=token[-8:],
    )
    return reason
