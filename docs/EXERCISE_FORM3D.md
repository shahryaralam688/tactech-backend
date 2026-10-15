# Exercise catalog + Form Studio 3D

Backend is the **source of truth** for the plan exercise library and optional Mixamo / Three.js demos.

## Character contract

- Mixamo **X_Bot** → `form3d.character = "x_bot"`
- Attribution: `form3d.attribution = "Mixamo"` when enabled (do not claim Adobe ownership)

## Client API

```http
GET /exercises
GET /exercises/{id}
Authorization: Bearer <JWT>
```

Each item includes legacy fields (`muscleGroup`, `equipment` string, `difficulty`, `cues`, `icon`) **plus**:

| Field | Notes |
|-------|--------|
| `category` | strength \| cardio \| mobility \| core \| … |
| `muscles` | string[] |
| `level` | beginner \| intermediate \| advanced |
| `equipmentList` | string[] tags (legacy `equipment` string kept for old clients) |
| `instructions` | long text |
| `commonMistakes` | string[] |
| `thumbnailUrl` | optional |
| `form3d.enabled` | **always present** — `false` hides iOS demo button |
| `form3d.clipId` | e.g. `push_up` — local FBX fallback key when `animationUrl` is null |
| `form3d.animationUrl` | absolute HTTPS FBX/GLB (preferred for new clips) |
| `form3d.guide` | `{ focus, title, detail, t, camera? }[]` |
| `form3d.cues` | short coaching lines for the player |

**iOS precedence:** if `form3d.enabled` → show demo (`animationUrl` HTTPS, else bundled asset keyed by `clipId`). Else hide button.

Stable ids (`ex-squat`, `ex-pushup`, …) are **never renamed**.

## Ops: add a Mixamo clip end-to-end

1. In Mixamo, download **FBX** for **X_Bot** (or convert to GLB).
2. Upload:

```http
POST /admin/form3d/uploads
X-Admin-Key: <ADMIN_API_KEY>
Content-Type: multipart/form-data
file: Push_Up.fbx
```

→ `{ "animationUrl": "https://…/form3d/x_bot/Push_Up_v….fbx", "key": "…", "contentType": "model/fbx" }`

3. Attach to catalog row:

```http
PUT /admin/exercises/{id}/form3d
X-Admin-Key: <ADMIN_API_KEY>
{
  "enabled": true,
  "clipId": "push_up",
  "character": "x_bot",
  "animationUrl": "https://cdn…/form3d/x_bot/Push_Up_v….fbx",
  "cues": ["Keep a rigid plank line"],
  "guide": [{ "focus": "Hands", "title": "Plant your hands", "detail": "…", "t": 0.08 }]
}
```

4. Optional: edit `data/exercises_form3d_seed.json` and run:

```bash
.venv/bin/python -m scripts.seed_exercise_form3d
```

5. Create a brand-new plan exercise (rare):

```http
POST /admin/exercises
X-Admin-Key: <ADMIN_API_KEY>
{ "id": "ex-new-move", "name": "…", "muscleGroup": "…", … }
```

Do **not** bulk-import thousands of Mixamo motions into the trainer plan catalog — keep it curated.

## Seed pack

`data/exercises_form3d_seed.json` — all 24 known ids with Mixamo queries + draft guides.

Form Studio-ready (enabled, local `clipId` until CDN URL is set):

| id | clipId |
|----|--------|
| ex-pushup | push_up |
| ex-plank | plank |
| ex-lunge | walking_lunge |
| ex-squat | barbell_squat |
| ex-rdl | romanian_deadlift |
| ex-hiphinge | hip_hinge |

Cardio rows stay `form3d.enabled = false`.

## Migration

```bash
alembic upgrade head   # 023_exercise_form3d
.venv/bin/python -m scripts.seed_exercise_form3d
```
