# Phase 3 — Trainee AI (Apple IAP)

AI Coach is gated behind Apple subscription. Trainer Boost (Stripe) is independent.

## Defaults
- `AI_FREE_TEASE_MESSAGES_PER_WEEK=0` → **hard paywall** (402 `AI_REQUIRED`)
- Set to `3` for a weekly free tease of 3 AI message sends

## SKUs (seed)

| id | appleProductId | period | amountMinor |
|----|----------------|--------|-------------|
| `ai.pro.monthly` | `ai.pro.monthly` | month | 999 |
| `ai.pro.yearly` | `ai.pro.yearly` | year | 7999 |

Create matching Auto-Renewable Subscriptions in App Store Connect (same product ids).

## Env

```bash
APPLE_BUNDLE_ID=com.yourcompany.tactech
APPLE_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
APPLE_KEY_ID=XXXXXXXXXX
APPLE_PRIVATE_KEY_P8="-----BEGIN PRIVATE KEY-----\n…\n-----END PRIVATE KEY-----"
APPLE_ENVIRONMENT=Sandbox
AI_FREE_TEASE_MESSAGES_PER_WEEK=0
```

## App Store Server Notifications V2

Point ASSN V2 URL to:

```text
https://<your-api>/billing/webhooks/apple
```

Handled: `SUBSCRIBED`, `DID_RENEW`, `DID_FAIL_TO_RENEW`, `GRACE_PERIOD_EXPIRED`, `EXPIRED`, `REFUND`, `REVOKE`, `TEST`, …

## QA flow

```bash
# Seed products
.venv/bin/alembic upgrade head && .venv/bin/python -m app.seed

# Optional complimentary AI (no StoreKit):
.venv/bin/python -m scripts.grant_ai --email trainee@tactech.app --days 30

# Products
curl -sS -H "Authorization: Bearer $TOKEN" "$BASE/billing/products?type=ai"

# After StoreKit 2 purchase on device:
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"signedTransaction":"<JWS>"}' "$BASE/billing/ai/apple/verify"

curl -sS -H "Authorization: Bearer $TOKEN" "$BASE/me/ai"
curl -sS -H "Authorization: Bearer $TOKEN" "$BASE/me/entitlements"
```

Without entitlement, `POST /coach/chat` → **402** `{ "detail": "…", "code": "AI_REQUIRED" }`.

## Gated vs free

| Gated (402) | Free (no AI) |
|-------------|--------------|
| `POST /coach/chat` | `GET /coach/conversations` |
| `POST /coach/chat/image` | `POST /coach/conversations` |
| `POST /coach/voice/turn` | human `/chat/*` |
| `POST /coach/rtc/sessions` | `/coaches`, contact |
| `POST /coach/memory/sync` | Boost Stripe routes |
