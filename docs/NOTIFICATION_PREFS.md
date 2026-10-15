# Notification Settings (all 10 toggles)

## Sample GET `/me/preferences/notifications`

```json
{
  "push": true,
  "aiCoach": false,
  "metrics": true,
  "vibrations": false,
  "sound": true,
  "appUpdate": true,
  "resources": false,
  "offersDevice": false,
  "chatMessages": true,
  "chatCalls": true
}
```

`PUT` accepts the full object or a partial patch (booleans only); re-GET always returns all 10 keys.

`vibrations` / `sound` — persisted for iOS local UX; **do not** affect APNs.

## Push tokens

- `POST /me/push-tokens` `{ "token", "platform": "ios", "deviceName?", "appVersion?" }`
- `DELETE /me/push-tokens` `{ "token" }`

## APNs gate table

| type | Pref required (after `push==true`) | Inbox + Socket |
|------|-------------------------------------|----------------|
| `chat` | `chatMessages` | always |
| `chat_call` | `chatCalls` | always |
| `ai_coach` | `aiCoach` | if pref on |
| `metrics` / `workout` | `metrics` | if pref on |
| `plan_assigned` / `plan_unassigned` / `plan_updated` | `metrics` | **always** |
| `app_update` | `appUpdate` | if pref on |
| `resources` | `resources` | if pref on |
| `offers` | `offersDevice` | if pref on (promo may skip inbox when off) |
| `join_request*` / `relationship_ended` / follow_* | master `push` only | **always** |

`push: false` → **zero** APNs of any type. Socket chat/call when online still works.
