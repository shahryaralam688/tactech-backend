# Join Request System (invite → pending → accept/reject)

**Breaking change:** `POST /trainee/link` no longer creates an active roster link. It is an **alias** of `POST /trainee/join-requests` and returns a **pending** join-request object. The trainer must **Accept** before `TraineeProfile.trainer_id` is set.

Minimum notify path: **REST inbox** (`GET /me/notifications`) + Socket `notification.created`. APNs is optional and never blocks this flow.

## Status machine

```
(none) → POST create → pending
pending → trainer Accept → accepted  (+ active link)
pending → trainer Reject → rejected  (no link)
pending → trainee Cancel → cancelled (no link)
accepted | rejected | cancelled → terminal
```

## Product rules

| Rule | HTTP | code |
|------|------|------|
| Already linked → create | 409 | `ALREADY_LINKED` |
| Already pending → create | 409 | `PENDING_EXISTS` |
| Unknown invite code | 404 | `INVITE_NOT_FOUND` |
| Wrong trainer Accept/Reject | 403 | `FORBIDDEN` |
| Non-pending transition | 400 | `VALIDATION_ERROR` |

One active trainer and one pending request per trainee max.

## Trainee APIs

### Create

```http
POST /trainee/join-requests
Authorization: Bearer <accessJWT>
Content-Type: application/json

{ "inviteCode": "TACT-OMAR", "message": "Hi — available evenings" }
```

`201`:

```json
{
  "id": "jr_…",
  "status": "pending",
  "inviteCode": "TACT-OMAR",
  "message": "Hi — available evenings",
  "createdAt": "…",
  "updatedAt": "…",
  "trainer": { "id": "user_…", "name": "Omar Hussain", "avatarUrl": null }
}
```

Does **not** set `trainerId` / roster.

### Alias (legacy)

```http
POST /trainee/link
{ "inviteCode": "TACT-OMAR" }
```

Same as create (pending `JoinRequestOut`). Message is always null.

### Mine

```http
GET /trainee/join-requests/mine
```

Returns `{ activeLink, pendingRequest }` (either/both may be null).

`GET /trainee/trainer` still returns the **active** linked trainer only (or `null`). Pending ≠ linked.

### Cancel

```http
POST /trainee/join-requests/{id}/cancel
→ { "id": "jr_…", "status": "cancelled" }
```

## Trainer APIs

```http
GET /trainer/join-requests?status=pending
POST /trainer/join-requests/{id}/accept
POST /trainer/join-requests/{id}/reject
Optional body: { "reason": "Roster full right now" }
```

Accept runs the same roster activation as the old successful link (`RosterLinkService.activate`): trainee appears on `GET /trainer/trainees`.

## Notifications

| type | recipient |
|------|-----------|
| `join_request` | trainer |
| `join_request_accepted` | trainee |
| `join_request_rejected` | trainee |

Inbox rows always created; Socket event `notification.created`. Unread count includes these.

## Signup with inviteCode

Signup with a valid `inviteCode` creates a **pending** join request after account creation. It does **not** auto-accept or set `trainerId`. Invalid codes are ignored (signup still succeeds).

## Leave / remove (unchanged)

- `POST /trainee/unlink` — trainee leaves **active** link  
- `POST /trainer/trainees/{traineeId}/remove` — trainer removes from roster  

Pending cancel is a different endpoint. Chat threads are never deleted on reject/cancel/leave/remove. Unassign plan ≠ leave.

## Migration

Alembic `025_join_requests` → table `join_requests` + partial unique index (one pending per `trainee_user_id` on Postgres).

```bash
alembic upgrade head
```

## OpenAPI (snippets)

```yaml
/trainee/join-requests:
  post:
    summary: Create pending join request
    responses:
      "201": { description: JoinRequestOut pending }
      "404": { description: INVITE_NOT_FOUND }
      "409": { description: ALREADY_LINKED | PENDING_EXISTS }
/trainee/link:
  post:
    summary: Alias of join-requests create (breaking — no longer auto-links)
    responses:
      "201": { description: JoinRequestOut pending }
/trainer/join-requests/{id}/accept:
  post:
    summary: Accept → active roster link
```
