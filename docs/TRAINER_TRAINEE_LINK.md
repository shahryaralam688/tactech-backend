# Trainer ↔ Trainee invite roster

Invite-code relationship lifecycle (v1: **one active trainer per trainee**).

> **Join requests:** Linking is no longer instant. See [JOIN_REQUESTS.md](./JOIN_REQUESTS.md).  
> `POST /trainee/link` creates a **pending** request; trainer **Accept** creates the active link.

## Request (pending)

```http
POST /trainee/join-requests
{ "inviteCode": "TACT-MAYA", "message": "optional" }

# Alias (same behavior):
POST /trainee/link
{ "inviteCode": "TACT-MAYA" }
```

- Empty code → `400 VALIDATION_ERROR`
- Unknown code → `404 INVITE_NOT_FOUND`
- Already linked → `409 ALREADY_LINKED` — *“You already have a trainer. Leave them first.”*
- Already pending → `409 PENDING_EXISTS`
- Success → **pending** only; `GET /trainee/trainer` still null; not on roster until Accept

```http
POST /trainer/join-requests/{id}/accept
```

Success → trainee on `GET /trainer/trainees`; `GET /trainee/trainer` returns coach.

## Leave / remove

```http
POST /trainee/unlink
Body: {} or empty (optional)
→ { "ok": true, "endedAt": "…Z", "trainerUserId": "…" }
```

404 when already unlinked: `{ "detail": "No trainer linked.", "code": "NOT_FOUND" }`

```http
POST /trainer/trainees/{traineeId}/remove
→ { "ok": true, "traineeId": "…", "endedAt": "…Z" }
```

`traineeId` may be trainee profile id **or** trainee user id.

**Side effects (both):**

1. Soft-end `trainer_trainee_links` (`status=ended`) — history kept  
2. Clear `TraineeProfile.trainer_id` (roster)  
3. Clear active **plan assignment** (`GET /trainee/assigned-plan` → null)  
4. **Chat threads/messages kept**  
5. Peer realtime (no APNs required):
   - Inbox `relationship_ended` (`reason`: `trainee_left` | `trainer_removed`)
   - Socket `notification.created` → room `user:{peerUserId}` (`/` + `/chat`)
   - Socket `relationship.changed` `{ action: "unlinked", reason, trainerUserId, traineeUserId, traineeProfileId, occurredAt }` → peer (+ actor multi-device)

Join **Accept** keeps `join_request_accepted` and also emits `relationship.changed` with `action: "linked"`, `reason: "join_accepted"`.

Unassign plan alone does **not** emit relationship events.

Second unlink → `404` *“No trainer linked.”*  
Wrong trainer removing another’s trainee → `403`.

## Status helpers

| Endpoint | Unlinked / pending behavior |
|----------|-----------------------------|
| `GET /trainee/trainer` | `200` with `null` (pending ≠ linked) |
| `GET /trainee/join-requests/mine` | `{ activeLink, pendingRequest }` |
| `GET /trainee/assigned-plan` | `200` with `null` when unlinked |
| `GET /trainer/trainees` | Only **active** roster (`trainer_id` set) |

Unassign plan alone does **not** end the relationship.

## Re-link

After leave/remove (or cancel/reject), trainee may create a new join request again.

## iOS notes

1. After Accept, refresh roster + assigned plan + trainer card.  
2. After unlink/remove, refresh the same; keep chat.  
3. Show toast from `detail` on 4xx.  
4. Treat pending UI separately from linked trainer card.
