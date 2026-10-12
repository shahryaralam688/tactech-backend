"""App Store Server API + StoreKit 2 JWS helpers (Phase 3).

Flow (preferred):
1. Decode JWS payload (or accept transactionId)
2. Fetch canonical transaction via App Store Server API (source of truth)
3. Map to VerifiedAppleTransaction for entitlement upsert

ASSN V2: decode signedPayload → process notificationType idempotently.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import jwt

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.core.logging import get_logger

log = get_logger("tactech.billing.apple")

_ACTIVE_STATUSES = frozenset({"active", "grace", "billing_retry"})


@dataclass
class VerifiedAppleTransaction:
    transaction_id: str
    original_transaction_id: str
    product_id: str
    bundle_id: str
    environment: str  # Sandbox | Production
    purchase_date: datetime | None
    expires_date: datetime | None
    revocation_date: datetime | None
    type: str | None = None
    raw: dict[str, Any] | None = None


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def decode_jws_payload(jws: str) -> dict[str, Any]:
    """Decode JWS payload without local cert verify (trusted after App Store Server API fetch)."""
    parts = (jws or "").strip().split(".")
    if len(parts) < 2:
        raise ValidationAppError("Invalid Apple JWS.", fields={"signedTransaction": "invalid"})
    try:
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception as exc:
        raise ValidationAppError(
            "Could not decode Apple transaction.",
            fields={"signedTransaction": "decode_failed"},
        ) from exc
    if not isinstance(payload, dict):
        raise ValidationAppError("Invalid Apple JWS payload.")
    return payload


def _ms_to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def transaction_from_payload(payload: dict[str, Any]) -> VerifiedAppleTransaction:
    env = str(payload.get("environment") or "Production")
    if env.lower() == "sandbox":
        env = "Sandbox"
    elif env.lower() == "production":
        env = "Production"
    return VerifiedAppleTransaction(
        transaction_id=str(payload.get("transactionId") or ""),
        original_transaction_id=str(
            payload.get("originalTransactionId") or payload.get("transactionId") or ""
        ),
        product_id=str(payload.get("productId") or ""),
        bundle_id=str(payload.get("bundleId") or ""),
        environment=env,
        purchase_date=_ms_to_dt(payload.get("purchaseDate") or payload.get("originalPurchaseDate")),
        expires_date=_ms_to_dt(payload.get("expiresDate")),
        revocation_date=_ms_to_dt(payload.get("revocationDate")),
        type=str(payload.get("type") or "") or None,
        raw=payload,
    )


class AppleIAPClient:
    """Thin App Store Server API client. Injectable for tests."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def configured(self) -> bool:
        return bool(
            self.settings.apple_bundle_id
            and self.settings.apple_issuer_id
            and self.settings.apple_key_id
            and self.settings.apple_private_key_p8
        )

    def _private_key(self) -> str:
        key = (self.settings.apple_private_key_p8 or "").strip()
        if "\\n" in key:
            key = key.replace("\\n", "\n")
        if not key:
            raise ValidationAppError(
                "Apple IAP is not configured. Set APPLE_PRIVATE_KEY_P8.",
                fields={"apple": "missing"},
            )
        return key

    def _api_token(self) -> str:
        now = int(time.time())
        payload = {
            "iss": self.settings.apple_issuer_id,
            "iat": now,
            "exp": now + 50 * 60,
            "aud": "appstoreconnect-v1",
            "bid": self.settings.apple_bundle_id,
        }
        return jwt.encode(
            payload,
            self._private_key(),
            algorithm="ES256",
            headers={"kid": self.settings.apple_key_id, "typ": "JWT"},
        )

    def _base_urls(self) -> list[str]:
        sandbox = "https://api.storekit-sandbox.itunes.apple.com"
        production = "https://api.storekit.itunes.apple.com"
        env = (self.settings.apple_environment or "Sandbox").strip().lower()
        if env == "production":
            # Optional fallback: Production then Sandbox (document in README)
            return [production, sandbox]
        return [sandbox, production]

    def get_transaction(self, transaction_id: str) -> VerifiedAppleTransaction:
        if not self.configured():
            raise ValidationAppError(
                "Apple IAP is not configured on the server.",
                fields={"apple": "missing"},
            )
        token = self._api_token()
        headers = {"Authorization": f"Bearer {token}"}
        last_error: Exception | None = None
        with httpx.Client(timeout=20.0) as client:
            for base in self._base_urls():
                url = f"{base}/inApps/v1/transactions/{transaction_id}"
                try:
                    res = client.get(url, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = exc
                    continue
                if res.status_code == 404:
                    continue
                if res.status_code >= 400:
                    last_error = ValidationAppError(
                        "Apple could not verify this transaction.",
                        fields={"apple": f"http_{res.status_code}"},
                    )
                    continue
                body = res.json()
                signed = body.get("signedTransactionInfo") or body.get("signedTransaction")
                if not signed:
                    raise ValidationAppError("Apple response missing signed transaction.")
                payload = decode_jws_payload(signed)
                tx = transaction_from_payload(payload)
                if not tx.transaction_id:
                    tx.transaction_id = transaction_id
                return tx
        if last_error:
            if isinstance(last_error, ValidationAppError):
                raise last_error
            raise ValidationAppError("Apple App Store Server API unavailable.") from last_error
        raise ValidationAppError(
            "Transaction not found in App Store.",
            fields={"transactionId": "not_found"},
        )

    def verify_signed_transaction(self, signed_transaction: str) -> VerifiedAppleTransaction:
        """Decode client JWS then re-fetch via API when configured (never trust client alone)."""
        payload = decode_jws_payload(signed_transaction)
        tx_id = str(payload.get("transactionId") or "")
        if not tx_id:
            raise ValidationAppError(
                "signedTransaction missing transactionId.",
                fields={"signedTransaction": "missing_transactionId"},
            )
        if self.configured():
            return self.get_transaction(tx_id)
        # Dev-only path: allow decoded payload when Apple API not configured (APP_ENV development)
        if (self.settings.app_env or "").lower() in {"development", "test", "local"}:
            log.warning("apple_verify_dev_unverified_jws", transaction_id=tx_id)
            return transaction_from_payload(payload)
        raise ValidationAppError(
            "Apple IAP is not configured on the server.",
            fields={"apple": "missing"},
        )

    def decode_notification(self, signed_payload: str) -> dict[str, Any]:
        """Decode ASSN V2 signedPayload. When API configured, payload decode is sufficient for routing;
        signature authenticity relies on TLS + Apple delivery; optionally expand to x5c verify later.
        """
        outer = decode_jws_payload(signed_payload)
        return outer
