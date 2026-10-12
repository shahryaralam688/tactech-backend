# Phase 2 — Trainer Boost (Stripe)

Boost is a **SaaS marketing fee** paid by trainers. Money goes to TacTech’s Stripe account (no Connect / marketplace split).

Pakistan JazzCash / Easypaisa (PKR): see [BILLING_LOCAL_PK.md](./BILLING_LOCAL_PK.md).

## SKUs

| id | duration | amountMinor | currency |
|----|----------|-------------|----------|
| `boost.featured.7d` | 7 days | 999 | usd (~$9.99) |
| `boost.featured.30d` | 30 days | 2499 | usd (~$24.99) |

## Env

```bash
STRIPE_SECRET_KEY=sk_test_…
STRIPE_WEBHOOK_SECRET=whsec_…
STRIPE_PUBLISHABLE_KEY=pk_test_…   # optional for Checkout URL flow
STRIPE_SUCCESS_URL=tactech://billing/boost/success?session_id={CHECKOUT_SESSION_ID}
STRIPE_CANCEL_URL=tactech://billing/boost/cancel
STRIPE_PRICE_BOOST_7D=price_…
STRIPE_PRICE_BOOST_30D=price_…
```

Then: `alembic upgrade head && python -m app.seed`

## Stripe Dashboard (test mode)

1. Create Product **Featured Boost — 7 days** → one-time Price $9.99 → copy `price_…` into `STRIPE_PRICE_BOOST_7D`
2. Create Product **Featured Boost — 30 days** → one-time Price $24.99 → `STRIPE_PRICE_BOOST_30D`
3. Re-seed so `billing_products.stripe_price_id` updates

## Stripe CLI webhook forward

```bash
stripe listen --forward-to localhost:8000/billing/webhooks/stripe
# copy whsec_… → STRIPE_WEBHOOK_SECRET, restart API
```

## QA flow

```bash
# 1) Login as trainer, list products
curl -sS -H "Authorization: Bearer $TOKEN" "$BASE/billing/products?type=boost"

# 2) Start checkout → open `url` in browser / ASWebAuthenticationSession
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"productId":"boost.featured.7d"}' "$BASE/billing/boost/checkout"

# 3) Pay with test card 4242… ; webhook activates boost
# Backup if webhook delayed:
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"checkoutSessionId":"cs_test_…"}' "$BASE/billing/boost/confirm"

# 4) Verify
curl -sS -H "Authorization: Bearer $TOKEN" "$BASE/me/boost"
curl -sS -H "Authorization: Bearer $TOKEN" "$BASE/me/entitlements"
# As any user: GET /coaches → that coach has boostActive:true and sorts first

# Complimentary staging boost (no Stripe):
.venv/bin/python -m scripts.grant_boost --email trainer@tactech.app --days 7

# Expiry cron:
.venv/bin/python -m scripts.expire_boosts
```

## Activation rules

- Source of truth: webhook `checkout.session.completed` or verified `POST /billing/boost/confirm`
- Stacking: if already active, `endsAt += duration` from **current endsAt**
- Idempotent: same `checkoutSessionId` never double-extends
- Refund: boost `status=refunded`, `endsAt=now`

## Future providers (Phase 2b)

`PaymentProvider` protocol in `app/services/billing/provider.py` — plug JazzCash / Easypaisa without changing boost activation.
