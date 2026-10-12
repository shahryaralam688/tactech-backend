# Phase 6 — Trainer Discovery Analytics

Privacy-safe discovery metrics for trainers (Boost ROI). **No viewer names/emails/ids** in API responses.

## Instrumentation

| Event | When |
|-------|------|
| `view` | Successful `GET /coaches/{id}` by non-owner |
| `contact` | Successful `POST /coaches/{id}/contact` |
| `contact_created` | Same, when `created: true` |
| `impression` | `POST /coaches/events/impressions` (≤50 ids; 1 per viewer↔coach / 15 min) |

Self traffic is ignored.

## Trainer APIs

```http
GET /me/coach-analytics?periodDays=30
GET /me/coach-analytics/summary?periodDays=7
```

`periodDays`: `7` | `30` | `90` only.

### Totals (charts)

- `views`, `uniqueViewers`, `impressions`, `contacts`, `contactsCreated`
- `ratingAvg` / `ratingCount` (Phase 5 snapshot)
- `boostActiveDays` — distinct UTC dates in period intersecting any boost window
- `series[]` — one UTC date bucket (zeros filled); omit on `/summary`
- `boost.activeNow` / `boost.endsAt`

## iOS notes

- Header widgets → `/summary`
- Line/bar charts → `series[].date` + `views` / `contacts` / `impressions`
- Never expect viewer identity lists
