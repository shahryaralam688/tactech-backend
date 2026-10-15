# TacTech — AI Gateway + Freemium (ONE COPY-PASTE DOC)

**Use:**  
- AI Gateway freemium: **PART A** (Backend) → **PART B** (iOS)  
- Plan edit/delete lock (sirf AI plans): **PART E** (Backend) → **PART F** (iOS)  

**Har implementing AI** ko us PART ke END pe Verification Report bhar ke deni hai.  
**Product owner** report Composer/reviewer ko bhejega taake andaza lage kaam ho gaya ya nahi.

Path: `docs/PROMPT_AI_GATEWAY_FREEMIUM.md` — isi file ko update / copy-paste karo.

---

# PART A — BACKEND PROMPT

You are a senior FastAPI engineer on **TacTech**.

## Mission

1. Add an **AI Gateway** (provider abstraction) so text AI is swappable via env.
2. Wire a **free text LLM now** (Gemini Flash free tier OR Groq — pick one, document it) for chat / summaries / structured plan generation.
3. Add **placeholder providers** for vision pose + food scan that return a stable error until paid keys exist.
4. Expose `GET /coach/ai/capabilities` so clients know what is live.
5. **Do not break** existing features: `/coach/chat`, memory sync, assessments, plans, boost, join-requests, packages, human `/chat/*`.
6. Freemium: quota / entitlement checks stay **separate** from which provider is used.
7. Keep all product features; only swap the intelligence engine behind the gateway.

**Auth:** Bearer JWT  
**JSON:** camelCase  
**Errors:** `{ "detail": "…", "code": "…" }`

---

## Architecture (required)

```
ai/
  gateway.py
  capabilities.py
  providers/
    text_gemini.py       # OR text_groq.py — ACTIVE free text
    text_openai.py       # PLACEHOLDER — disabled if OPENAI_API_KEY empty
    vision_pose_stub.py
    vision_food_stub.py
  schemas/workout_plan_out.py
```

Env example:

```
AI_TEXT_PROVIDER=gemini
GEMINI_API_KEY=...
GROQ_API_KEY=
OPENAI_API_KEY=
AI_VISION_POSE_PROVIDER=stub
AI_VISION_FOOD_PROVIDER=stub
AI_FREE_CHAT_DAILY_LIMIT=10
AI_FREE_PLAN_GENERATIONS=1
```

- Factory selects text provider from `AI_TEXT_PROVIDER` (`gemini` | `groq` | `openai`).
- If selected provider key missing → 503 `{ "code": "AI_PROVIDER_NOT_CONFIGURED" }`.
- `text_openai.py` must implement the **same interface** as Gemini/Groq so flipping env later needs **no caller rewrites**.

---

## Capabilities

### `GET /coach/ai/capabilities`

Authenticated. Reflect real config:

```json
{
  "textChat": true,
  "structuredPlanJson": true,
  "weeklySummary": true,
  "visionPose": false,
  "visionFood": false,
  "textProvider": "gemini",
  "visionPoseProvider": "stub",
  "visionFoodProvider": "stub",
  "freeChatDailyLimit": 10,
  "freePlanGenerations": 1
}
```

If pose/food are stubs → those booleans **false**.

---

## Gateway behavior

### Text (live)

- Existing `/coach/chat` must call gateway text chat; **SSE contract unchanged** for iOS.
- Keep assessment/memory context injection.
- Free daily chat quota unless AI Pro/Advanced entitlement; over quota → **402** `{ "code": "AI_QUOTA_EXCEEDED", "detail": "…" }`.

### Structured plan (new, additive)

### `POST /coach/programs/generate`

```json
{ "horizonDays": 7, "notes": "optional" }
```

Rules:

- Load trainee assessment + exercise catalog.
- LLM returns JSON compatible with iOS `WorkoutPlan` (days + exercises with **real** `exerciseId`s).
- Validate IDs; one retry; else 422.
- If trainee already has an active trainer link → **409** `{ "code": "HAS_TRAINER", "detail": "…" }` (solo generate only when no trainer).
- Free: `AI_FREE_PLAN_GENERATIONS` (default 1 — document lifetime vs monthly).
- Then further generates → **402**.
- Advanced/Pro: allow regenerate.
- Do not delete human trainer plans for linked trainees (blocked by 409).

### Optional thin

### `POST /coach/programs/weekly-summary`

Text LLM + logs; document free vs Advanced rule.

### Vision placeholders

### `POST /coach/vision/pose`

### `POST /coach/vision/food`

While stub, consistent error (use **501** OR **503**, pick one and stick to it):

```json
{
  "detail": "Pose AI is not configured yet. Coming soon.",
  "code": "AI_CAPABILITY_UNAVAILABLE",
  "capability": "visionPose"
}
```

Food: `capability: "visionFood"`.

---

## Do not break

`/trainee/assessment`, `/trainer/assessment`, `/coach/memory/sync`, Boost billing, join-requests, notifications, `/chat/*`, existing coach SSE shapes.

---

## Product freemium reminder (backend enforce only quotas)

- Core coaching (link, plans, human chat) stays available without AI pay.
- AI chat cap + plan generate quota drive Advanced/Pro.
- Boost remains separate product.

---

## MANDATORY OUTPUT — Backend Verification Report

When finished, your reply MUST include this block filled in (product owner will forward it for review):

```
## TacTech AI Gateway — Verification Report

### A) Provider config
- Active text provider: (gemini|groq|openai)
- Text live? (YES/NO)
- OPENAI placeholder class exists? (YES/NO)
- Pose provider: ___ | visionPose: (true/false)
- Food provider: ___ | visionFood: (true/false)

### B) Routes
- GET /coach/ai/capabilities sample JSON: (paste)
- POST /coach/programs/generate success HTTP: ___
- Vision pose stub HTTP ___ code ___
- Vision food stub HTTP ___ code ___

### C) Existing chat
- /coach/chat still SSE? (YES/NO)
- Free quota enforced? (YES/NO) limit: ___
- Over quota code: ___

### D) Solo generate
- Free generations policy: ___
- Has trainer → ___
- Exercise IDs validated? (YES/NO)

### E) Files touched
- (paths)

### F) Switch to paid OpenAI later (3 steps)
1. ___
2. ___
3. ___

### G) Manual tests
1. capabilities GET: PASS/FAIL
2. chat one message: PASS/FAIL
3. generate plan once: PASS/FAIL
4. generate again free (expect 402): PASS/FAIL
5. pose stub: PASS/FAIL
6. food stub: PASS/FAIL
7. boost/join/human chat smoke: PASS/FAIL

### H) Honest gaps
- ___
```

---

# PART B — iOS PROMPT

You are a senior SwiftUI engineer on **TacTech Trainer iOS**.

## Mission

1. **Keep all existing features** (AI chat UI, Boost, join requests, plans, Form Studio, packages, human chat, assessment).
2. Consume `GET /coach/ai/capabilities` and cache.
3. Soft-gate AI chat on 402 / quota → existing AI paywall.
4. Additive Solo trainee UX when **no trainer**: “Train with AI” / **Generate my week** → `POST /coach/programs/generate`; handle 402 paywall, 409 HAS_TRAINER.
5. Pose / Food: if capabilities false OR `AI_CAPABILITY_UNAVAILABLE` → **Coming soon** (no crash). Add minimal placeholder entry if missing.
6. Optional **Free vs Advanced** info sheet (copy only).

Do not remove Boost, human chat, trainer assign, Form Studio, or join flows.

---

## API client

- `GET /coach/ai/capabilities`
- `POST /coach/programs/generate`
- Map 402 → AI paywall; 409 → toast; 501/503 + `AI_CAPABILITY_UNAVAILABLE` → Coming soon

---

## UX

- No trainer → Generate my week card
- Has trainer → no solo generate (or explain use trainer plan)
- Free vs Advanced short sheet available from Account/AI
- Vision screens: “Advanced · Coming soon” until capability true

---

## MANDATORY OUTPUT — iOS Verification Report

```
## TacTech iOS AI Freemium — Verification Report

### A) Capabilities
- Fetches capabilities? (YES/NO)
- Cached where: ___

### B) Features preserved
- Boost? (YES/NO)
- Join requests? (YES/NO)
- Human chat? (YES/NO)
- Form Studio? (YES/NO)
- Trainer plan assign? (YES/NO)

### C) Solo generate
- Entry when no trainer? (YES/NO) screen: ___
- POST generate? (YES/NO)
- 402 → paywall? (YES/NO)
- 409 handled? (YES/NO)

### D) Chat quota
- 402 → paywall? (YES/NO)

### E) Placeholders
- Pose coming soon if visionPose false? (YES/NO)
- Food coming soon if visionFood false? (YES/NO)

### F) Files touched
- (paths)

### G) Manual QA
1. No trainer → AI generate entry: PASS/FAIL
2. Generate → workout updates: PASS/FAIL
3. Second free generate → paywall: PASS/FAIL
4. Chat until cap → paywall: PASS/FAIL
5. Pose/food coming soon no crash: PASS/FAIL
6. Boost/join still OK: PASS/FAIL

### H) Gaps
- ___
```

---

# PART C — HOW YOU (PRODUCT OWNER) USE THIS

1. Copy **PART A** only into Backend AI → get Backend Verification Report.
2. Copy **PART B** only into iOS AI → get iOS Verification Report.
3. Paste both reports back to Composer/reviewer and ask: “andaza lagaao kaam ho gaya ya nahi.”
4. **Plan edit/delete lock:** Copy **PART E** (Backend) then **PART F** (iOS). Same report → review flow.

---

# PART D — CHANGE LOG

| Date | Change |
|------|--------|
| 2026-10-15 | Initial one-box doc — AI Gateway + freemium + stubs + dual verification reports. Saved as `docs/PROMPT_AI_GATEWAY_FREEMIUM.md`. |
| 2026-10-15 | Backend PART A shipped: `app/ai/` gateway (Gemini primary free text / Groq / OpenAI placeholder), capabilities + generate + vision stubs (501), freemium daily chat + lifetime plan gens. Sanitize/remap + Groq 429 retry later same day. |
| 2026-10-16 | PART E/F — Only AI-generated plans may be edited/deleted by trainee; trainer plans locked (`source` field). |
| 2026-10-16 | Backend PART E shipped: `workout_plans.source` + `owner_trainee_id`; generate=`ai`; trainer create=`trainer`; `PATCH|DELETE /trainee/ai-plans/{id}` (delete → 204); assigned-plan returns `source`. |
| 2026-10-16 | Doc synced with full PART F iOS prompt (source UX + ai-plans API). |

---

# PART E — BACKEND PROMPT (AI plan edit/delete only)

You are a senior FastAPI engineer on **TacTech**.

## Product rule (international)

| Plan type | Who may PATCH/DELETE | Who may unassign |
|-----------|----------------------|------------------|
| **AI solo** (`source=ai`) | Owning **trainee** | Owning trainee (clear assignment) |
| **Trainer plan** (`source=trainer`) | Owning **trainer** only | **Trainer** unassign only |
| Trainee on trainer plan | **Read-only** — 403 on edit/delete | No |

Core coaching: trainee must **not** rewrite a human coach’s program.

## Mission

1. Persist plan origin: `source: "ai" | "trainer"` (required on create).
2. `POST /coach/programs/generate` → save with `source: "ai"`, `trainerId` null/empty, owner = trainee user/profile.
3. Trainer `POST /trainer/plans` → `source: "trainer"`.
4. Enforce on:
   - `PATCH /trainer/plans/{id}` / trainee edit route if any
   - `DELETE /trainer/plans/{id}` or trainee delete-AI route
5. `GET /trainee/assigned-plan` must return `source` so iOS can hide Edit/Delete.

**Auth:** Bearer JWT · **JSON:** camelCase  
**Errors:** `{ "detail": "…", "code": "…" }`

| HTTP | code | when |
|------|------|------|
| 403 | `PLAN_LOCKED` | Trainee tries edit/delete trainer plan |
| 403 | `FORBIDDEN` | Wrong owner |
| 404 | `NOT_FOUND` | Missing plan |

### Suggested trainee AI routes (additive OK)

- `PATCH /trainee/ai-plans/{id}` — only if `source=ai` and owner
- `DELETE /trainee/ai-plans/{id}` — only if `source=ai` and owner; clear assignment

Or reuse plan PATCH/DELETE with role checks — document which.

### Assigned-plan payload (add field)

```json
{
  "id": "…",
  "source": "ai",
  "trainerId": null,
  "title": "…",
  "days": []
}
```

Trainer-assigned: `"source": "trainer"`, `trainerId` set.

### Migration

Existing plans: if created via generate / no trainerId → `ai`; else `trainer`.

### Do not break

Assign/unassign trainer flows, generate, chat, boost, join-requests.

---

## MANDATORY OUTPUT — Backend Verification Report

```
## Plan source lock — Backend Verification Report

### A) Source field
- source on plans? (YES/NO)
- generate sets source=ai? (YES/NO)
- trainer create sets source=trainer? (YES/NO)
- GET assigned-plan includes source? (YES/NO)

### B) Enforcement
- trainee PATCH trainer plan → 403 PLAN_LOCKED? (YES/NO)
- trainee DELETE ai plan → 200? (YES/NO)
- trainer PATCH own plan still works? (YES/NO)

### C) Routes used
- Trainee AI edit: ___
- Trainee AI delete: ___

### D) Files touched
- ___

### E) Gaps
- ___
```

---

# PART F — iOS PROMPT (AI plan edit/delete only)

You are a senior SwiftUI engineer on **TacTech Trainer iOS**.

## Rule

- If assigned plan `source == "ai"` (or equivalent): show **Edit** / **Delete** / regenerate for trainee.
- If `source == "trainer"` OR trainee has linked trainer with that plan: **no** edit/delete — read-only; copy: “Assigned by your trainer”.
- Trainer app: keep existing edit/delete for **their** plans only.

## Model

Extend `WorkoutPlan` with optional:

```swift
var source: String? // "ai" | "trainer"
```

Decode safely; if missing: treat as `trainer` if `trainerId` non-empty, else `ai`.

## API

- Prefer `PATCH /trainee/ai-plans/{id}` and `DELETE /trainee/ai-plans/{id}` if backend ships them.
- Else document fallback paths backend returns.
- Map 403 `PLAN_LOCKED` → toast with server `detail`.

## UX

- Workout hub / plan detail: Edit & Delete only when `plan.source == "ai"` (and not locked by active trainer assignment of a trainer plan).
- Delete confirm → delete AI plan API → clear local assignment → show **Generate my week** card again.
- Edit → existing plan editor or lightweight editor calling PATCH AI plan.
- Trainer-assigned plan: hide Edit/Delete; optional label “Assigned by your trainer”.

## Do not

- Let trainee PATCH/DELETE trainer plans
- Remove trainer CreatePlan / delete on trainer side
- Break Boost, join, Form Studio, AI chat, generate flow

---

## MANDATORY OUTPUT — iOS Verification Report

```
## Plan source lock — iOS Verification Report

### A) Model
- source decoded? (YES/NO)
- missing source fallback rule: ___

### B) UX
- AI plan shows Edit/Delete? (YES/NO)
- Trainer plan hides Edit/Delete? (YES/NO)
- Delete AI → generate card returns? (YES/NO)
- 403 PLAN_LOCKED toast? (YES/NO)

### C) Features preserved
- Trainer plan CRUD? (YES/NO)
- Generate my week? (YES/NO)
- Boost / join? (YES/NO)

### D) Files touched
- ___

### E) Gaps
- ___
```
