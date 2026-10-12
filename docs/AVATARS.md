# Profile avatars — CDN source of truth

## iOS precedence

1. **`avatarUrl`** (absolute `https://…`) → show custom photo  
2. else **`avatarAsset`** (catalog id, e.g. `Avatar_01_Color`)  
3. else **initials**

Never prefer catalog over a non-null `avatarUrl`.

## APIs

| Method | Path | Behavior |
|--------|------|----------|
| POST | `/me/avatar` | Multipart image ≤5MB → JPEG ≤1024px when possible; **new unique URL** every upload; clears `avatarAsset`; returns `avatarUrl` + `user`/`profile` snapshot |
| PATCH | `/me/profile` `{ avatarAsset }` | Sets catalog; **clears** custom `avatarUrl` + deletes object |
| DELETE | `/me/avatar` | Clears custom photo; restores `DEFAULT_AVATAR_ASSET` (`Avatar_01_Color`) if asset empty |
| GET | `/me`, `/me/profile` | Always absolute `avatarUrl` when custom exists (`PUBLIC_BASE_URL` / CDN) |

## Env

```bash
PUBLIC_BASE_URL=https://your-api.example.com   # required for absolute local/uploads URLs

# Optional object storage (AWS S3 / Cloudflare R2 / GCS S3 API)
MEDIA_S3_BUCKET=
MEDIA_S3_REGION=auto
MEDIA_S3_ENDPOINT_URL=          # R2 endpoint if used
MEDIA_S3_ACCESS_KEY_ID=
MEDIA_S3_SECRET_ACCESS_KEY=
MEDIA_CDN_BASE_URL=https://cdn.example.com
MEDIA_S3_PREFIX=avatars
DEFAULT_AVATAR_ASSET=Avatar_01_Color
```

When S3 is configured, uploads go to the bucket and `avatarUrl` is `MEDIA_CDN_BASE_URL/.../v_{unix}_{id}.jpg`.  
When not configured, files live under `uploads/avatars/{userId}/v_…jpg` and are absolutized with `PUBLIC_BASE_URL`.

## Cache-bust

Every upload uses a **new object key** (`v_{timestamp}_{random}`). Old objects are deleted best-effort so CDN/browser cannot stick on the previous URL.
