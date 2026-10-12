# TacTech Coach + Human Chat — Backend Notes

## Architecture

| Channel | API | Realtime | Purpose |
|---------|-----|----------|---------|
| AI Coach | `/coach/*` | SSE + RTC signaling WS | Trainer/trainee AI |
| Human DM | `/chat/*` | Socket.IO + `/chat/rtc/*` | Trainer ↔ trainee 1:1 |
| Support | `/support/*` | Poll (`after`) | Help Center (unchanged) |

JWT scopes all ownership. Never trust body IDs for access.

**ASGI entrypoint:** `uvicorn app.main:asgi_app` (FastAPI + Socket.IO).  
`app.main:app` still works for HTTP-only (no Socket.IO).

---

## Notifications (in-app + push)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/me/push-tokens` | Register APNs/FCM device token |
| GET | `/me/push-tokens` | List this user’s devices |
| DELETE | `/me/push-tokens` | Body `{ token }` unregister |
| GET | `/me/notifications` | Inbox `{ items, nextCursor, unreadCount }` |
| GET | `/me/notifications/unread-count` | Badge |
| POST | `/me/notifications/read` | `{ notificationId? }` — omit = mark all |
| POST | `/me/notifications/delete` | `{ notificationId? }` — one id, or null/omit = clear all; returns `{ unreadCount }` (idempotent) |
| GET/PUT | `/me/preferences/notifications` | Includes `chatMessages`, `chatCalls`, master `push` |

Socket: `notification.created` (full inbox row) to personal room `user:{userId}` when a row is created.  
Remote APNs skipped when peer is Socket-online (foreground); still written to inbox.  
APNs: set `APNS_*` env — see [NOTIFICATIONS.md](./NOTIFICATIONS.md).

---

## Human chat — iOS wiring

### Auth
```
Authorization: Bearer <accessJWT>
```

### Canonical peer id
- **Prefer `peerUserId` = `User.id`** (from `/auth/login` → `user.id`, or peer’s user id in roster payloads).
- Also accepted (resolved server-side):
  - `peerTraineeProfileId` → TraineeProfile.id
  - `peerTrainerProfileId` → TrainerProfile.id
  - If `peerUserId` is actually a profile id, server resolves it when User.id lookup fails.

### REST
| Method | Path | Notes |
|--------|------|-------|
| GET | `/chat/threads` | Inbox; threads with ≥1 message only |
| POST | `/chat/threads` | `{ peerUserId }` → 200 existing / 201 created |
| GET | `/chat/threads/{id}/messages?cursor=&limit=50` | Older-than cursor |
| POST | `/chat/threads/{id}/messages` | JSON text / `call_event` **or** multipart media; optional `replyToMessageId` |
| POST | `/chat/threads/{id}/messages/upload` | Deprecated alias for multipart |
| POST | `/chat/threads/{id}/read` | `{ upToMessageId }` — also sets `deliveredAt` if null |
| POST | `/chat/threads/{id}/delivered` | `{ upToMessageId }` — grey double-check |
| POST | `/chat/threads/{id}/messages/{mid}/played` | Voice only; sets `playedAt` once |
| POST | `/chat/threads/{id}/messages/{mid}/reactions` | `{ emoji }` — one emoji per user |
| DELETE | `/chat/threads/{id}/messages/{mid}/reactions/{emoji}` | Remove own reaction |
| PATCH | `/chat/threads/{id}/messages/{mid}` | Edit own text within 15 min |
| DELETE | `/chat/threads/{id}/messages/{mid}?scope=everyone` | Soft-delete within 1 hour (sender); `scope=me` → 204 local-only |
| GET | `/chat/rtc/ice-servers` | `{ iceServers: [...] }` |
| GET | `/chat/rtc/incoming` | Active ringing sessions for me (REST fallback) |
| POST | `/chat/rtc/sessions` | `{ threadId }` → signalingPath + iceServers; emits `chat.call.incoming` to peer |
| WS | `/chat/rtc/sessions/{id}/signal?token=` | offer / answer / ice-candidate / hangup; `joined` broadcast to peers |

### Message DTO (additive WhatsApp fields)
Optional on every message: `deliveredAt`, `playedAt`, `replyToMessageId`, `replyToText`, `replyToSenderName`, `reactions[]`, `editedAt`, `deletedForEveryoneAt`. Existing fields unchanged.

### Multipart fields
`file`, optional `text`, `attachmentType` (`image`\|`video`\|`voice`\|`file`), `durationSeconds`, `clientId`, `kind`, `replyToMessageId`.

Limits: image 8MB, video 50MB, voice 5MB / ~60s, file 15MB.

### Socket.IO
- URL: same host `/socket.io` (namespace default `/`)
- Auth: `auth: { token: accessToken }` or `Authorization: Bearer …` on handshake
- Client → server: `chat.join` `{threadId}`, `chat.leave`, `chat.typing` `{threadId,isTyping}`, `chat.delivered` `{threadId,upToMessageId}`, `chat.played` `{threadId,messageId}`, `chat.react` / `chat.unreact` `{threadId,messageId,emoji}`
- Server → client: `chat.message`, `chat.thread.updated`, `chat.read`, `chat.delivered`, `chat.played`, `chat.reaction`, `chat.message.deleted`, `chat.typing`, `chat.call.incoming`, `chat.call.ended`
- Connect on `/` **or** namespace `/chat`; on connect you join personal room `user:{userId}` so calls ring on Home.
- `chat.call.incoming` payload includes `signalingPath`, `fromUserId`, `fromName`.
- Push `type=chat_call` (high priority) when peer is **not** Socket-connected.
- Typing is forwarded to thread peers only (`skip_sid` — no echo to sender).

### Example curls

```bash
BASE=http://127.0.0.1:8000
TOKEN=…   # trainer access JWT
PEER=…    # trainee User.id

# Create / find thread
curl -sS -X POST "$BASE/chat/threads" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"peerUserId\":\"$PEER\"}"

# Text
curl -sS -X POST "$BASE/chat/threads/$THREAD/messages" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"See you at 5","clientId":"ios-uuid-1"}'

# Image
curl -sS -X POST "$BASE/chat/threads/$THREAD/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@photo.jpg;type=image/jpeg" -F "attachmentType=image" -F "clientId=ios-uuid-2"

# Voice
curl -sS -X POST "$BASE/chat/threads/$THREAD/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@note.m4a;type=audio/mp4" -F "attachmentType=voice" -F "durationSeconds=12"

# Read
curl -sS -X POST "$BASE/chat/threads/$THREAD/read" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"upToMessageId":"m9"}'

# RTC
curl -sS -X POST "$BASE/chat/rtc/sessions" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"threadId\":\"$THREAD\"}"
```

### Test accounts (local seed)
| Role | Email | Password |
|------|-------|----------|
| Trainer | `trainer@tactech.app` | `SEED_TRAINER_PASSWORD` (default `trainer123`) |
| Trainee | `trainee@tactech.app` | `SEED_TRAINEE_PASSWORD` (default `trainee123`) |

Roster-linked after seed. Staging URL = your deploy / ngrok `PUBLIC_BASE_URL`.

### Deviations / notes
- Validation error code remains `VALIDATION_ERROR` (existing TacTech shape); chat RTC WS uses `VALIDATION` for signal parse errors.
- Push is queued/logged until APNs/FCM credentials are configured (`device_push_tokens` table ready).
- Soft-delete message endpoint deferred (v1.1).
- Human RTC is **separate** from `/coach/rtc/*`. Hangup inserts a `call_event` message for both sides.

---

## Coach discovery follow / hire (Phase 9)

Free marketplace link — see [COACH_FOLLOWS.md](./COACH_FOLLOWS.md).  
Accept upserts the same `TraineeProfile.trainer_id` roster link as `POST /trainee/link`. Contact / package inquire remain independent and do not create a roster link.

## Coach (unchanged summary)

See OpenAPI `/docs` and prior coach sections. SSE + `/coach/rtc/*` for AI call shell.
