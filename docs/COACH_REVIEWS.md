# Phase 5 — Coach Reviews & Ratings

Trainees rate public coaches (1–5 stars). Discovery shows `ratingAvg` / `ratingCount`. Boost still ranks above rating.

## Eligibility (Option A)

Trainee may review if coach `isPublic == true` **or** invite-linked to that trainer.  
No chat-thread or payment required.

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| POST | `/coaches/{id}/reviews` | trainee → **201** |
| PUT | `/coaches/{id}/reviews/me` | trainee author |
| DELETE | `/coaches/{id}/reviews/me` | trainee author |
| GET | `/coaches/{id}/reviews` | any logged-in |
| GET | `/coaches/{id}/reviews/me` | trainee → `{ "review": null \| … }` |
| POST | `/coaches/reviews/{reviewId}/report` | any logged-in (not author) |

## Aggregates

Denormalized on `coach_profiles` (`ratingAvg`, `ratingCount`). Recomputed on create/update/delete/hide.  
API exposes `ratingAvg` to **one decimal** (e.g. `4.7`); `null` when count=0.

## Moderation

Reports stored in `coach_review_reports` (unique per reporter↔review).  
Auto-hide after **≥3** distinct reports; aggregates exclude hidden.

## Sort

`boostActive DESC` → `ratingAvg DESC NULLS LAST` → `ratingCount DESC` → `updatedAt DESC`.

## iOS fields

Add to coach list/detail/`/me/coach-profile`: `ratingAvg`, `ratingCount`.  
Review DTOs: `authorName` (first name only), `isMine`, `stars`, `body`.
