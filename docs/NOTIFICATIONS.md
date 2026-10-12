# Instant notifications — Socket.IO + APNs

## Flow (order matters)

1. Insert `app_notifications` row (unread)
2. Emit Socket.IO **`notification.created`** to the recipient’s personal room
3. Best-effort **APNs** to registered iOS device tokens (skipped if recipient is Socket-online for chat/follow, or prefs off)
4. Push failures never fail the originating request (chat send / follow / etc.)

## Socket rooms

| Room | Who joins | Events |
|------|-----------|--------|
| `user:{userId}` | On Socket connect (JWT) | `notification.created`, `chat.call.incoming`, … |
| `chat:{threadId}` | After `chat.join` | `chat.message`, typing, reactions, … |

Connect with `auth: { token: "<accessJWT>" }` on `/` or `/chat`.

### `notification.created` payload

Same shape as `GET /me/notifications` items (camelCase):

```json
{
  "id": "n_123",
  "type": "chat",
  "title": "New message",
  "body": "What’s my next workout?",
  "createdAt": "2026-10-11T18:00:00.000Z",
  "readAt": null,
  "data": { "type": "chat", "threadId": "th_1", "messageId": "m_9" }
}
```

## APNs env

| Variable | Notes |
|----------|--------|
| `APNS_KEY_ID` | Key ID from Apple Developer |
| `APNS_TEAM_ID` | Team ID |
| `APNS_BUNDLE_ID` | App bundle id (falls back to `APPLE_BUNDLE_ID`) |
| `APNS_PRIVATE_KEY_P8` | `.p8` PEM contents (`\n` for newlines in `.env`) |
| `APNS_ENVIRONMENT` | `sandbox` (default) or `production` |

If unset: inbox + Socket still work; server logs `apns_not_configured` once. Invalid tokens (`BadDeviceToken` / `Unregistered`) are deleted from `device_push_tokens`.

Register tokens: `POST /me/push-tokens` `{ token, platform: "ios" }`.

## AI 402 (Subscribe CTA)

Blocked AI routes return:

```json
{
  "detail": "AI Coach Pro is required to continue.",
  "code": "AI_REQUIRED",
  "action": "subscribe",
  "productHint": "ai.pro.monthly"
}
```

`productHint` from `AI_PRODUCT_HINT` (default `ai.pro.monthly`).

## QA checklist

- [ ] Unpaid AI → 402 + `action: subscribe`
- [ ] Paid AI → 200
- [ ] A messages B (B socket connected) → B gets `notification.created` quickly; unread bumps
- [ ] B background + valid APNs token → device alert (sandbox)
- [ ] Push failure does not break chat send
- [ ] `POST /me/notifications/delete` + read still work
