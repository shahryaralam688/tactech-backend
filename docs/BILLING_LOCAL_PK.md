# Phase 4 — Pakistan Boost (JazzCash + Easypaisa)

Trainer Boost can be paid with **Stripe (USD)** or **JazzCash / Easypaisa (PKR)**.  
Activation rules match Phase 2 (extend `endsAt` if already active). Idempotent IPNs.

## Money units

| Store | Unit | Example |
|-------|------|---------|
| DB `amountMinor` for PKR | **paisa** (×100) | `299900` = PKR **2,999.00** |
| JazzCash `pp_Amount` | paisa string | `"299900"` |
| Easypaisa `transactionAmount` | rupees with decimals | `"2999.00"` |

USD Stripe products still use cents (`999` = $9.99).

## Seeded SKUs

| id | currency | providers | amountMinor |
|----|----------|-----------|-------------|
| `boost.featured.7d` | usd | stripe | 999 |
| `boost.featured.30d` | usd | stripe | 2499 |
| `boost.featured.7d.pkr` | pkr | jazzcash, easypaisa | 299900 |
| `boost.featured.30d.pkr` | pkr | jazzcash, easypaisa | 799900 |

## Env

```bash
PUBLIC_BASE_URL=https://xxxx.ngrok-free.app   # required for auto-POST pay page

JAZZCASH_MERCHANT_ID=…
JAZZCASH_PASSWORD=…
JAZZCASH_INTEGRITY_SALT=…
JAZZCASH_CHECKOUT_URL=https://sandbox.jazzcash.com.pk/CustomerPortal/transactionmanagement/merchantform/
JAZZCASH_RETURN_URL=tactech://billing/boost/success
JAZZCASH_IPN_URL=https://xxxx.ngrok-free.app/billing/webhooks/jazzcash

EASYPAISA_STORE_ID=…
EASYPAISA_HASH_KEY=…
EASYPAISA_CHECKOUT_URL=…
EASYPAISA_RETURN_URL=tactech://billing/boost/success
EASYPAISA_IPN_URL=https://xxxx.ngrok-free.app/billing/webhooks/easypaisa

BOOST_SUCCESS_URL=tactech://billing/boost/success?attempt_id={ATTEMPT_ID}
```

## Mobile flow

1. `POST /billing/boost/checkout` `{ "productId": "boost.featured.7d.pkr", "provider": "jazzcash" }`
2. Open returned `url` (`/billing/boost/pay/{attemptId}`) in Safari / ASWebAuthenticationSession  
   → server auto-POSTs form to wallet hosted page
3. Wallet IPN → `/billing/webhooks/jazzcash` or `/easypaisa` → `activate_boost`
4. App return: `POST /billing/boost/confirm` `{ "attemptId": "…" }` (refresh; IPN is source of truth)

## QA matrix

| Case | Expect |
|------|--------|
| USD + stripe | Phase 2 regression green |
| PKR + stripe | 400 unsupported provider |
| JazzCash valid hash IPN | `/me/boost.active true` |
| Tampered hash | 400, no activate |
| Duplicate IPN | no double extend |
| Easypaisa paid | activate |
| AI Apple routes | unchanged |
