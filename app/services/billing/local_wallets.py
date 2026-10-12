"""JazzCash + Easypaisa hosted checkout helpers (Phase 4).

Money convention (documented):
- DB `amountMinor` for PKR = **paisa** (PKR × 100), same as USD cents.
- JazzCash `pp_Amount` = paisa string (no decimal), e.g. 299900 → PKR 2,999.00
- Easypaisa amount field = rupees with 2 decimals string, e.g. "2999.00"
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from app.core.config import Settings
from app.core.exceptions import ProviderError, ValidationAppError
from app.core.logging import get_logger

log = get_logger("tactech.billing.local")


@dataclass
class LocalCheckoutResult:
    attempt_id: str
    provider: str
    url: str
    merchant_txn_id: str
    form_fields: dict[str, str] = field(default_factory=dict)
    provider_checkout_url: str = ""


@dataclass
class LocalPaymentResult:
    provider: str
    paid: bool
    merchant_txn_id: str
    provider_payment_id: str
    amount_minor: int | None = None
    currency: str = "pkr"
    raw: dict[str, Any] = field(default_factory=dict)
    failure_message: str | None = None


def amount_minor_to_jazzcash_pp_amount(amount_minor: int) -> str:
    """JazzCash expects integer paisa as string."""
    return str(int(amount_minor))


def amount_minor_to_easypaisa_rupees(amount_minor: int) -> str:
    """Easypaisa hosted often wants rupees with 2 decimals."""
    return f"{int(amount_minor) / 100.0:.2f}"


def jazzcash_secure_hash(fields: dict[str, str], integrity_salt: str) -> str:
    """HMAC-SHA256 over salt + sorted non-empty values (JazzCash MWALLET page pattern)."""
    pairs = []
    for key in sorted(fields.keys()):
        if key == "pp_SecureHash":
            continue
        val = fields.get(key)
        if val is None or str(val) == "":
            continue
        pairs.append(str(val))
    message = "&".join([integrity_salt] + pairs)
    digest = hmac.new(
        integrity_salt.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest.upper()


def easypaisa_secure_hash(
    *,
    store_id: str,
    amount_rupees: str,
    order_id: str,
    hash_key: str,
) -> str:
    """SHA256(storeId + amount + orderId + hashKey) — common Easypaisa merchant pattern."""
    raw = f"{store_id}{amount_rupees}{order_id}{hash_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


class JazzCashBoostProvider:
    name = "jazzcash"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def configured(self) -> bool:
        return bool(
            self.settings.jazzcash_merchant_id
            and self.settings.jazzcash_password
            and self.settings.jazzcash_integrity_salt
            and self.settings.jazzcash_checkout_url
        )

    def build_checkout(
        self,
        *,
        attempt_id: str,
        merchant_txn_id: str,
        amount_minor: int,
        description: str,
        return_url: str,
        public_pay_base: str,
    ) -> LocalCheckoutResult:
        if not self.configured():
            raise ValidationAppError(
                "JazzCash is not configured. Set JAZZCASH_* env vars.",
                fields={"jazzcash": "missing"},
            )
        now = datetime.now(timezone.utc)
        txn_datetime = now.strftime("%Y%m%d%H%M%S")
        # Bill expiry +1 day
        from datetime import timedelta

        expiry = (now + timedelta(days=1)).strftime("%Y%m%d%H%M%S")
        fields = {
            "pp_Version": "1.1",
            "pp_TxnType": "MWALLET",
            "pp_Language": "EN",
            "pp_MerchantID": self.settings.jazzcash_merchant_id,
            "pp_Password": self.settings.jazzcash_password,
            "pp_TxnRefNo": merchant_txn_id,
            "pp_Amount": amount_minor_to_jazzcash_pp_amount(amount_minor),
            "pp_TxnCurrency": "PKR",
            "pp_TxnDateTime": txn_datetime,
            "pp_BillReference": attempt_id[:20],
            "pp_Description": (description or "TacTech Boost")[:100],
            "pp_TxnExpiryDateTime": expiry,
            "pp_ReturnURL": return_url or self.settings.jazzcash_return_url,
            "pp_SecureHash": "",
        }
        fields["pp_SecureHash"] = jazzcash_secure_hash(
            fields, self.settings.jazzcash_integrity_salt
        )
        # Mobile opens our auto-post page (keeps password out of client query logs when possible)
        pay_url = f"{public_pay_base.rstrip('/')}/billing/boost/pay/{attempt_id}"
        return LocalCheckoutResult(
            attempt_id=attempt_id,
            provider=self.name,
            url=pay_url,
            merchant_txn_id=merchant_txn_id,
            form_fields=fields,
            provider_checkout_url=self.settings.jazzcash_checkout_url,
        )

    def verify_ipn(self, form: dict[str, Any]) -> LocalPaymentResult:
        if not self.configured():
            raise ValidationAppError("JazzCash is not configured.")
        data = {k: str(v) for k, v in form.items() if v is not None}
        received = (data.get("pp_SecureHash") or "").upper()
        expected = jazzcash_secure_hash(data, self.settings.jazzcash_integrity_salt)
        if not received or not hmac.compare_digest(received, expected):
            log.warning("jazzcash_bad_hash")
            raise ValidationAppError(
                "Invalid JazzCash payment signature.",
                fields={"jazzcash": "bad_signature"},
            )
        if data.get("pp_MerchantID") != self.settings.jazzcash_merchant_id:
            raise ValidationAppError("JazzCash merchant mismatch.")

        response_code = data.get("pp_ResponseCode") or data.get("pp_ResponseCode".lower()) or ""
        # 000 = success in JazzCash
        paid = str(response_code) in {"000", "00", "121"}
        merchant_txn = data.get("pp_TxnRefNo") or ""
        provider_payment = data.get("pp_RetreivalReferenceNo") or data.get("pp_TxnRefNo") or merchant_txn
        amount_raw = data.get("pp_Amount")
        amount_minor = int(amount_raw) if amount_raw and str(amount_raw).isdigit() else None
        return LocalPaymentResult(
            provider=self.name,
            paid=paid,
            merchant_txn_id=merchant_txn,
            provider_payment_id=str(provider_payment),
            amount_minor=amount_minor,
            currency="pkr",
            raw=data,
            failure_message=None if paid else (data.get("pp_ResponseMessage") or "Payment failed"),
        )


class EasypaisaBoostProvider:
    name = "easypaisa"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def configured(self) -> bool:
        return bool(
            self.settings.easypaisa_store_id
            and self.settings.easypaisa_hash_key
            and self.settings.easypaisa_checkout_url
        )

    def build_checkout(
        self,
        *,
        attempt_id: str,
        merchant_txn_id: str,
        amount_minor: int,
        description: str,
        return_url: str,
        public_pay_base: str,
    ) -> LocalCheckoutResult:
        if not self.configured():
            raise ValidationAppError(
                "Easypaisa is not configured. Set EASYPAISA_* env vars.",
                fields={"easypaisa": "missing"},
            )
        amount_rupees = amount_minor_to_easypaisa_rupees(amount_minor)
        token = easypaisa_secure_hash(
            store_id=self.settings.easypaisa_store_id,
            amount_rupees=amount_rupees,
            order_id=merchant_txn_id,
            hash_key=self.settings.easypaisa_hash_key,
        )
        fields = {
            "storeId": self.settings.easypaisa_store_id,
            "orderId": merchant_txn_id,
            "transactionAmount": amount_rupees,
            "mobileAccountNo": "",
            "emailAddress": "",
            "transactionType": "MA",  # mobile account / hosted
            "tokenHash": token,
            "merchantPaymentMethod": "",
            "postBackURL": return_url or self.settings.easypaisa_return_url,
            "signature": token,
        }
        pay_url = f"{public_pay_base.rstrip('/')}/billing/boost/pay/{attempt_id}"
        return LocalCheckoutResult(
            attempt_id=attempt_id,
            provider=self.name,
            url=pay_url,
            merchant_txn_id=merchant_txn_id,
            form_fields=fields,
            provider_checkout_url=self.settings.easypaisa_checkout_url,
        )

    def verify_ipn(self, form: dict[str, Any]) -> LocalPaymentResult:
        if not self.configured():
            raise ValidationAppError("Easypaisa is not configured.")
        data = {k: str(v) for k, v in form.items() if v is not None}
        order_id = data.get("orderId") or data.get("order_id") or ""
        amount_rupees = data.get("transactionAmount") or data.get("amount") or ""
        store_id = data.get("storeId") or self.settings.easypaisa_store_id
        received = (
            data.get("tokenHash") or data.get("signature") or data.get("secureHash") or ""
        ).upper()
        expected = easypaisa_secure_hash(
            store_id=store_id,
            amount_rupees=amount_rupees,
            order_id=order_id,
            hash_key=self.settings.easypaisa_hash_key,
        )
        if not received or not hmac.compare_digest(received, expected):
            log.warning("easypaisa_bad_hash")
            raise ValidationAppError(
                "Invalid Easypaisa payment signature.",
                fields={"easypaisa": "bad_signature"},
            )
        status = (data.get("transactionStatus") or data.get("status") or "").upper()
        paid = status in {"PAID", "SUCCESS", "COMPLETED", "000"}
        provider_payment = data.get("transactionId") or data.get("rrn") or order_id
        # Convert rupees string back to paisa
        amount_minor = None
        try:
            amount_minor = int(round(float(amount_rupees) * 100))
        except (TypeError, ValueError):
            pass
        return LocalPaymentResult(
            provider=self.name,
            paid=paid,
            merchant_txn_id=order_id,
            provider_payment_id=str(provider_payment),
            amount_minor=amount_minor,
            currency="pkr",
            raw=data,
            failure_message=None if paid else (data.get("responseMessage") or "Payment failed"),
        )


def html_auto_post_form(*, action: str, fields: dict[str, str], title: str) -> str:
    inputs = "\n".join(
        f'<input type="hidden" name="{_esc(k)}" value="{_esc(v)}" />' for k, v in fields.items()
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>{_esc(title)}</title></head>
<body>
<p>Redirecting to payment…</p>
<form id="pay" method="POST" action="{_esc(action)}">
{inputs}
</form>
<script>document.getElementById('pay').submit();</script>
</body></html>"""


def _esc(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
