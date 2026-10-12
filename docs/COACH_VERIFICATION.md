# Phase 7 — Coach Verification & Trust Badges

Free trust layer: trainers submit ID + certification; admin approves → `isVerified` badge on discovery.

## Env

```bash
ADMIN_API_KEY=your-long-random-admin-key
VERIFY_DOC_RETENTION_DAYS=90   # keep docs after approved|rejected; then soft-delete URLs/files
VERIFY_UPLOAD_MAX_BYTES=10485760
PUBLIC_BASE_URL=https://xxxx.ngrok-free.app   # so uploadUrl is reachable from device
```

## Upload flow (local “presign”)

1. `POST /me/coach-verification/uploads` → `{ uploadId, uploadUrl, fileKey, fileUrl, expiresAt }`
2. Client **PUT** raw bytes to `uploadUrl` with `Authorization: Bearer …`
3. `POST /me/coach-verification/applications` with those `fileKey`s

Files land under `uploads/verify/{userId}/…`. Not returned on public `/coaches`.

## Trainer APIs

| Method | Path |
|--------|------|
| GET | `/me/coach-verification` |
| POST | `/me/coach-verification/uploads` |
| PUT | `/me/coach-verification/uploads/{uploadId}` |
| POST | `/me/coach-verification/applications` |
| POST | `/me/coach-verification/cancel` |

## Admin APIs (`X-Admin-Key: $ADMIN_API_KEY`)

```bash
# Queue
curl -H "X-Admin-Key: $ADMIN_API_KEY" \
  "$BASE/admin/coach-verification/applications?status=submitted"

# Approve
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" \
  "$BASE/admin/coach-verification/applications/{id}/approve"

# Reject
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Certification unreadable."}' \
  "$BASE/admin/coach-verification/applications/{id}/reject"

# Revoke badge
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" \
  "$BASE/admin/coach-verification/revoke/{coachProfileId}"
```

## Public DTO

`/coaches` + detail + `/me/coach-profile`: `isVerified`, optional `verifiedBadge: "Verified Coach"`.

Sort: boost → ratingAvg → **isVerified** → ratingCount → updatedAt.

## Staging seeds

- Maya Cole (`cp-maya`): `isVerified=true`
- Ali: sample **rejected** application + reason for UI QA

## Retention

After `approved` or `rejected`, retain documents for `VERIFY_DOC_RETENTION_DAYS` (default 90).  
Ops can delete files under `uploads/verify/` older than retention; DB URLs may be nulled by a future cleanup job.
