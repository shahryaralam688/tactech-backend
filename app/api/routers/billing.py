from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import HTMLResponse

from app.api.deps import (
    Principal,
    get_ai_billing_service,
    get_billing_service,
    get_principal,
    require_trainer,
)
from app.schemas.billing import (
    AppleRestoreRequest,
    AppleVerifyRequest,
    AppleWebhookAck,
    BillingProductPage,
    BoostCheckoutOut,
    BoostCheckoutRequest,
    BoostConfirmRequest,
    LocalWebhookAck,
    MeAiOut,
    MeBoostOut,
    StripeWebhookAck,
)
from app.services.ai_billing_service import AiBillingService
from app.services.billing_service import BillingService

router = APIRouter(tags=["billing"])


@router.get("/billing/products", response_model=BillingProductPage)
def list_billing_products(
    _: Annotated[Principal, Depends(get_principal)],
    service: Annotated[BillingService, Depends(get_billing_service)],
    type: Annotated[str | None, Query()] = "boost",
    currency: Annotated[str | None, Query()] = None,
) -> BillingProductPage:
    return service.list_products(type=type, currency=currency)


@router.post("/billing/boost/checkout", response_model=BoostCheckoutOut)
def create_boost_checkout(
    payload: BoostCheckoutRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> BoostCheckoutOut:
    return service.create_boost_checkout(principal, payload)


@router.post("/billing/boost/confirm", response_model=MeBoostOut)
def confirm_boost_checkout(
    payload: BoostConfirmRequest,
    principal: Annotated[Principal, Depends(require_trainer)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> MeBoostOut:
    return service.confirm_boost_checkout(principal, payload)


@router.post("/billing/webhooks/stripe", response_model=StripeWebhookAck)
async def stripe_webhook(
    request: Request,
    service: Annotated[BillingService, Depends(get_billing_service)],
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> StripeWebhookAck:
    """No JWT — Stripe signature verification only. Raw body required."""
    payload = await request.body()
    result = service.handle_stripe_webhook(payload, stripe_signature)
    return StripeWebhookAck(received=bool(result.get("received", True)))


@router.get("/billing/boost/pay/{attempt_id}", response_class=HTMLResponse)
def boost_pay_redirect(
    attempt_id: str,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> HTMLResponse:
    """Auto-POST form to JazzCash/Easypaisa hosted page (opened by iOS Safari)."""
    return HTMLResponse(content=service.pay_page_html(attempt_id))


@router.post("/billing/webhooks/jazzcash", response_model=LocalWebhookAck)
async def jazzcash_ipn(
    request: Request,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> LocalWebhookAck:
    """JazzCash IPN — no JWT; verify pp_SecureHash."""
    form = await request.form()
    data: dict[str, Any] = {k: str(v) for k, v in form.items()}
    if not data:
        # Some sandboxes POST JSON
        try:
            data = await request.json()
        except Exception:
            data = {}
    result = service.handle_jazzcash_ipn(data)
    return LocalWebhookAck(received=True, status=result.get("status"))


@router.post("/billing/webhooks/easypaisa", response_model=LocalWebhookAck)
async def easypaisa_ipn(
    request: Request,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> LocalWebhookAck:
    """Easypaisa IPN — no JWT; verify tokenHash/signature."""
    form = await request.form()
    data: dict[str, Any] = {k: str(v) for k, v in form.items()}
    if not data:
        try:
            data = await request.json()
        except Exception:
            data = {}
    result = service.handle_easypaisa_ipn(data)
    return LocalWebhookAck(received=True, status=result.get("status"))


@router.post("/billing/ai/apple/verify", response_model=MeAiOut)
def verify_apple_ai(
    payload: AppleVerifyRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AiBillingService, Depends(get_ai_billing_service)],
) -> MeAiOut:
    return service.verify_for_user(
        principal,
        signed_transaction=payload.signed_transaction,
        signed_renewal_info=payload.signed_renewal_info,
        transaction_id=payload.transaction_id,
        original_transaction_id=payload.original_transaction_id,
    )


@router.post("/billing/ai/apple/restore", response_model=MeAiOut)
def restore_apple_ai(
    payload: AppleRestoreRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AiBillingService, Depends(get_ai_billing_service)],
) -> MeAiOut:
    txs = [
        {
            "signedTransaction": t.signed_transaction,
            "transactionId": t.transaction_id,
            "originalTransactionId": t.original_transaction_id,
        }
        for t in payload.transactions
    ]
    return service.restore_for_user(principal, txs)


@router.post("/billing/webhooks/apple", response_model=AppleWebhookAck)
async def apple_webhook(
    request: Request,
    service: Annotated[AiBillingService, Depends(get_ai_billing_service)],
) -> AppleWebhookAck:
    """App Store Server Notifications V2 — no JWT; verify signedPayload."""
    raw = await request.body()
    result = service.handle_apple_notification(raw)
    return AppleWebhookAck(received=bool(result.get("received", True)))
