# Phase 8 — Coach Packages (Listings + Inquire)

Trainers publish **informational** service packages. Trainees **inquire** → human chat.  
**No platform payment or commission in this phase.**

## Money (display only)

| Currency | `amountMinor` | Example |
|----------|---------------|---------|
| `pkr` | paisa (×100) | `1500000` → **PKR 15,000** |
| `usd` | cents | `9900` → **$99.00** |

## Trainer APIs

| Method | Path |
|--------|------|
| GET | `/me/coach-packages` |
| POST | `/me/coach-packages` |
| PUT | `/me/coach-packages/{id}` |
| POST | `/me/coach-packages/{id}/archive` |

Max **20** active packages; max **1** featured per coach.

## Public / trainee

| Method | Path |
|--------|------|
| GET | `/coaches/{id}/packages` |
| GET | `/coaches/{id}/packages/{packageId}` |
| POST | `/coaches/{id}/packages/{packageId}/inquire` |

Inquire returns `{ threadId, peerUserId, packageId, created }` and posts:
`I'm interested in your package "{title}" ({priceLabel}).`

iOS: open human chat with `threadId` (same as contact).

## Discovery summary

`packagesCount` + optional `featuredPackage` on list/detail/`/me/coach-profile`.
