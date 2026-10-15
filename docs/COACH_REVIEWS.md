# Coach Reviews & Ratings (roster-only)

Marketplace coach profiles show **only reviews from that coach’s trainees**.  
Create / edit / delete require an **active** roster link (post join-Accept). After Leave/Remove, historical reviews stay visible but edits are blocked.

## Eligibility

```text
canReview = role==trainee
         AND caller != coach.userId
         AND trainee.trainer_id == coach.trainer_id
            (or active trainer_trainee_links row)
```

| reason | meaning |
|--------|---------|
| `OK` | may create/edit/delete |
| `NOT_ROSTERED` | not currently linked |
| `NOT_TRAINEE_ROLE` | trainer / wrong role |
| `IS_SELF` | coach viewing self |

Write failures → `403` with `code: "NOT_ELIGIBLE"`  
detail: `"Only current trainees of this coach can leave a review."`

## Endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET | `/coaches/{id}/reviews/me` | `{ review, canReview, reason }` — any auth |
| POST | `/coaches/{id}/reviews` | roster only → 201 |
| PUT | `/coaches/{id}/reviews/me` | roster only |
| DELETE | `/coaches/{id}/reviews/me` | roster only |
| GET | `/coaches/{id}/reviews` | public list; averages = eligible-only |
| POST | `/coaches/reviews/{id}/report` | any auth (not author) |

## Migration

`026_reviews_roster_only` — deletes reviews whose author was **never** linked to that coach (no current `trainer_id` match and no `trainer_trainee_links` history), then recomputes `ratingAvg` / `ratingCount`.  
Staging run purged **10** orphan rows. Leave/remove does **not** delete reviews.

## Aggregates

Denormalized on `coach_profiles`. Recomputed on create/update/delete/hide.  
`ratingAvg` to one decimal; `null` when count=0.

## iOS

Use `canReview` to show/hide Write/Edit. If `review != null && canReview == false`, show review read-only.
