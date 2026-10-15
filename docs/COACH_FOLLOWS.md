# Phase 9 — Marketplace Follow / Hire (Free)

Trainees can **Follow / Hire** a public coach from discovery. On accept (or auto-accept), the backend creates the **same** trainer↔trainee roster link as invite-code (`TraineeProfile.trainer_id`). **No payment.**

## Follow vs invite vs contact vs inquire

| Action | Endpoint | Creates roster link? | Chat? |
|--------|----------|----------------------|-------|
| **Follow / hire** | `POST /coaches/{id}/follow` | Yes, after accept (or immediately if `followMode=auto_accept`) | Prefer reuse/create human thread + context message |
| **Invite code** | `POST /trainee/join-requests` (alias: `/trainee/link`) → trainer Accept | After Accept only | No (unless already chatting) |
| **Contact** | `POST /coaches/{id}/contact` | No | Yes |
| **Package inquire** | `POST /coaches/{id}/packages/{pkg}/inquire` | No | Yes + package interest text |

Contact and inquire stay free and independent of follow.

## Trainee APIs

| Method | Path |
|--------|------|
| POST | `/coaches/{id}/follow` |
| GET | `/coaches/{id}/follow` |
| POST | `/coaches/{id}/follow/cancel` |
| POST | `/me/coach-follow/end` |

Body (optional): `{ "note": "…", "packageId": "pkg1" }` — package is context only.

## Trainer APIs

| Method | Path |
|--------|------|
| GET | `/me/coach-follows?status=pending` |
| POST | `/me/coach-follows/{id}/accept` |
| POST | `/me/coach-follows/{id}/decline` |
| POST | `/me/coach-follows/{id}/end` |

`followMode` on `GET/PUT/PATCH /me/coach-profile`: `manual` (default) | `auto_accept`.

## Discovery

`GET /coaches/{id}` for a trainee includes `followStatus`: `none` | `pending` | `active` | `declined` | `ended`. Also exposes `followMode` for UI (“Instant accept”).

## Rules (v1)

- One open (`pending`/`active`) relationship per trainee.
- Same coach already linked (invite or follow) → `409` `ALREADY_LINKED`.
- Ending unlinks roster; **chat history is kept**.
- Coach must be public for **new** follows; existing active links remain if they go private.
