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
| 2026-10-16 | PART G/H added — AI Tool Calling for trainer automation + trainee memory awareness. Core sellable AI feature. |

---

# PART G — BACKEND PROMPT (AI Tool Calling — Trainer Automation)

You are a senior FastAPI engineer on **TacTech**.

## Context — What is already built

The following files already exist and are SHIPPED. **Do not rewrite them.** This prompt describes what they do so you can verify, fix bugs, or extend.

### Architecture (already in place)

```
app/ai/
  gateway.py              # Provider factory — auto-selects groq/gemini/openai/mock from env
  tools.py                # 10 tool definitions + ToolExecutor class (NEW)
  providers/
    base.py               # TextLLMProvider base — has complete() + complete_with_tools() + stream()
    text_groq.py           # Groq provider — complete_with_tools() sends tools + tool_choice: "auto"
    text_gemini.py         # Gemini provider
    text_openai.py         # OpenAI placeholder
    text_mock.py           # Mock (returns canned response, no tool support)

app/services/
  coach_service.py         # CoachService — chat() and stream_chat() with _complete_with_tool_loop()
  ai/memory.py             # MemoryService — _trainer_chunks() loads ALL trainer data as RAG context
  ai_access.py             # Freemium quota gate — daily/weekly limits, entitlement checks
  trainer_service.py       # TrainerService — real CRUD for trainees, plans, feedback
  join_request_service.py  # JoinRequestService — accept/reject join requests
```

### How it works (the flow)

1. **Trainer sends message** → `POST /coach/chat` or `/coach/stream-chat`
2. **Memory loaded** → `_trainer_chunks()` builds RAG context with ALL trainer data:
   - Trainee roster (names, goals, calories, assigned plans)
   - All workout plans authored by trainer
   - Trainee workout activity (total workouts, duration, last session)
   - Trainer feedback given
   - Form reports (exercise scores)
   - Join requests (pending/accepted/rejected)
   - Coach profile (headline, city, specialties, rating, verified)
   - Coach reviews, followers, packages
   - Chat thread summary
3. **System prompt** tells the AI it can take actions using tools
4. **`_complete_with_tool_loop()`** runs up to 5 rounds:
   - Calls `complete_with_tools()` with `TRAINER_TOOLS` list
   - If LLM returns `tool_calls` → `ToolExecutor.execute()` runs each one
   - Tool results appended to messages → next LLM call
   - Continues until LLM returns text content with no tool calls
5. **ToolExecutor** dispatches to real `TrainerService` / `JoinRequestService` methods

### 10 Tools available to trainer AI

| Tool | What it does | Service method |
|------|-------------|----------------|
| `list_trainees` | List all trainees with names, goals, plans | `TrainerService.list_trainees()` |
| `list_plans` | List all workout plans by trainer | `TrainerService.list_plans()` |
| `create_plan` | Create new plan (title, focus, level, days) | `TrainerService.create_plan()` |
| `assign_plan` | Assign plan to trainee | `TrainerService.assign_plan()` |
| `unassign_plan` | Remove trainee's plan | `TrainerService.unassign_plan()` |
| `send_feedback` | Send feedback message to trainee | `TrainerService.save_feedback()` |
| `list_join_requests` | List pending join requests | `JoinRequestService.list_for_trainer()` |
| `accept_join_request` | Accept a join request | `JoinRequestService.accept()` |
| `reject_join_request` | Reject with optional reason | `JoinRequestService.reject()` |
| `remove_trainee` | Remove trainee from roster | `TrainerService.remove_trainee()` |

### Trainee AI (no tools, memory-only)

Trainee AI does NOT have tool calling. It uses RAG memory context only:
- Their assigned plan and exercises
- Workout logs and progress
- Coach feedback received
- Goals, calories, meals
- Form reports

Trainee AI answers questions like "What's my workout today?", "Am I on track?", form tips, nutrition guidance.

### Freemium (already enforced)

| | Free | Subscribed (Apple IAP) |
|---|---|---|
| AI chat messages | `AI_FREE_CHAT_DAILY_LIMIT` (default 10/day) | Unlimited |
| AI plan generation | `AI_FREE_PLAN_GENERATIONS` (default 1 lifetime) | Unlimited |
| Tool actions | Within chat limit | Unlimited |
| Over limit | 402 `AI_QUOTA_EXCEEDED` | N/A |

### Env config

```env
# Provider (auto = try gemini → groq → openai → mock)
AI_TEXT_PROVIDER=auto
GROQ_API_KEY=gsk_...          # Free tier: 30 req/min, 14400/day

# Freemium limits
AI_FREE_CHAT_DAILY_LIMIT=10
AI_FREE_TEASE_MESSAGES_PER_WEEK=0
AI_FREE_PLAN_GENERATIONS=1
```

## What to verify / extend

If you are asked to work on this feature, here is what to check:

1. **Tool calling works end-to-end**: trainer says "list my trainees" → AI calls `list_trainees` tool → returns real data
2. **Multi-step chains work**: "assign my first plan to Ahmed" → AI calls `list_trainees` + `list_plans` → picks correct IDs → calls `assign_plan`
3. **Memory context is complete**: trainer asks "how is Ahmed doing?" → AI has Ahmed's workout logs, plan, feedback in RAG context
4. **Trainee AI has no tools**: trainee can only ask questions, not take actions
5. **Freemium gate fires**: free user hits daily limit → 402 → paywall
6. **Streaming**: trainers use tool loop (non-streaming until final response), trainees use SSE streaming

## Do not break

`/coach/chat` SSE contract, `/coach/stream-chat`, memory sync, trainee assessment, plan source lock, boost billing, join requests, human `/chat/*`.

---

## MANDATORY OUTPUT — Backend Tool Calling Verification Report

```
## AI Tool Calling — Backend Verification Report

### A) Tool calling
- complete_with_tools() on provider? (YES/NO)
- _complete_with_tool_loop() in CoachService? (YES/NO)
- Max tool rounds: ___
- Tools count: ___

### B) Tools working
- list_trainees returns real data? (YES/NO)
- list_plans returns real data? (YES/NO)
- create_plan creates in DB? (YES/NO)
- assign_plan assigns? (YES/NO)
- send_feedback saves? (YES/NO)
- accept_join_request works? (YES/NO)

### C) Memory context
- Trainer chunks include: roster / plans / logs / feedback / join requests / reviews / profile? (YES/NO)
- Trainee chunks include: plan / logs / goals / feedback? (YES/NO)

### D) Roles
- Trainer gets tools? (YES/NO)
- Trainee gets tools? (NO = correct)

### E) Freemium
- Daily limit enforced? (YES/NO) limit: ___
- Over limit → 402? (YES/NO)

### F) Files involved
- (paths)

### G) Manual tests
1. "List my trainees" → tool call → real data: PASS/FAIL
2. "Create a beginner strength plan" → plan in DB: PASS/FAIL
3. "Assign it to my first trainee" → multi-step chain: PASS/FAIL
4. "How is [trainee] doing?" → memory answer: PASS/FAIL
5. Trainee asks question → no tool call, memory answer: PASS/FAIL
6. Free user hits limit → 402: PASS/FAIL

### H) Gaps
- ___
```

---

# PART H — iOS PROMPT (AI Tool Calling — Frontend Support)

You are a senior SwiftUI engineer on **TacTech Trainer iOS**.

## Context — What the backend does

The backend AI now has **tool calling**. When a trainer asks the AI to do something (list trainees, create plan, assign plan, send feedback, accept/reject join requests), the AI executes it on the backend and replies with confirmation.

**This is invisible to the frontend.** The AI chat API (`POST /coach/chat` and `/coach/stream-chat`) works exactly the same — trainer sends a message, gets a text response back. The tool execution happens server-side between the user's message and the AI's reply.

## What the frontend needs to do

### 1. Nothing changes in the chat UI

The chat API contract is unchanged. The AI response may take slightly longer (1-3 extra seconds) because the backend runs tool calls before responding. No timeout changes needed — existing timeouts are sufficient.

### 2. Suggested prompts (already in app)

The app already shows suggestion chips: `"Draft a 4-day plan"`, `"Check trainee progress"`, `"Write form cues"`.

**Update or add these suggested prompts for trainers** to showcase the AI's action capabilities:

```swift
// Trainer suggestions — showcase tool calling
[
    "List all my trainees",
    "Create a beginner strength plan",
    "Show pending join requests",
    "How is my trainee doing?"
]
```

For trainees, keep motivational/informational suggestions:
```swift
[
    "What's my workout today?",
    "Am I on track this week?",
    "Give me form tips",
    "Nutrition ideas for my goal"
]
```

### 3. Handle data changes after AI actions

When the AI assigns a plan, accepts a join request, or creates a plan, the **data on other screens changes**. The frontend should:

- **Refresh trainee list** after returning from AI chat (the AI may have accepted a join request → new trainee appeared)
- **Refresh plans list** after returning from AI chat (the AI may have created a new plan)
- **Refresh assigned plan** for trainee (the AI may have assigned/unassigned)

Implementation: trigger a data refresh when the user navigates back from the AI chat screen. This can be a simple `onAppear` reload or a notification-based approach.

### 4. Paywall — already working

402 `AI_QUOTA_EXCEEDED` → show existing AI paywall. No changes needed.

### 5. Toast for AI actions (optional enhancement)

When the AI's response mentions it took an action ("I've assigned the plan" / "Feedback sent"), the frontend could show a subtle success indicator. This is optional — the AI's text reply already confirms the action.

## Do not break

- Existing chat UI, SSE streaming, message history
- Boost, join requests, plan management screens
- Form Studio, human chat, trainer plan assign
- Assessment flow

## Do not

- Add any tool-calling logic on the frontend — it's 100% backend
- Change the chat API contract
- Add new API endpoints — everything uses existing `/coach/chat` and `/coach/stream-chat`

---

## MANDATORY OUTPUT — iOS Tool Calling Verification Report

```
## AI Tool Calling — iOS Verification Report

### A) Chat UI
- Chat still works with longer AI responses? (YES/NO)
- SSE streaming preserved? (YES/NO)
- Message history unchanged? (YES/NO)

### B) Suggested prompts
- Trainer suggestions updated for actions? (YES/NO)
- Trainee suggestions updated for guidance? (YES/NO)

### C) Data refresh
- Trainee list refreshes after chat? (YES/NO)
- Plans list refreshes after chat? (YES/NO)
- Assigned plan refreshes? (YES/NO)

### D) Paywall
- 402 → paywall still works? (YES/NO)

### E) Features preserved
- Boost? (YES/NO)
- Join requests? (YES/NO)
- Human chat? (YES/NO)
- Form Studio? (YES/NO)
- Plan management? (YES/NO)

### F) Files touched
- (paths)

### G) Manual QA
1. Trainer sends "list my trainees" → gets real list back: PASS/FAIL
2. Trainer sends "create a plan" → plan appears in plans list: PASS/FAIL
3. Trainee asks "what's my workout" → gets answer: PASS/FAIL
4. Chat paywall at limit: PASS/FAIL
5. All other screens still work: PASS/FAIL

### H) Gaps
- ___
```

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
