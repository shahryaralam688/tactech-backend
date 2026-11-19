# TacTech Backend — AI Features Implementation Prompt

You are a senior FastAPI engineer on **TacTech**.

**Auth:** Bearer JWT · **JSON:** camelCase · **Errors:** `{ "detail": "…", "code": "…" }`

---

## 1. WHAT THE APP DOES

TacTech has two user types:

- **Trainer**: manages trainees, creates plans, gives feedback — AI automates all of this through chat
- **Trainee**: follows plans, logs workouts, asks AI for guidance — AI knows their plan, progress, goals

The AI is the **core paid feature**. Everything else (linking, plans, chat) is free. AI chat + AI plan generation drive the subscription.

---

## 2. AI GATEWAY — Provider Abstraction

### Architecture

```
app/ai/
  gateway.py              # Factory — auto-selects provider from env
  tools.py                # 10 trainer tool definitions + ToolExecutor class
  providers/
    base.py               # TextLLMProvider abstract base — complete() + complete_with_tools() + stream()
    text_groq.py           # Groq (free tier) — primary provider
    text_gemini.py         # Gemini Flash (free tier) — fallback
    text_openai.py         # OpenAI — placeholder for paid upgrade
    text_mock.py           # Mock — returns canned response (dev only, no tool support)
    vision_pose_stub.py    # Stub — returns 501 "Coming soon"
    vision_food_stub.py    # Stub — returns 501 "Coming soon"
```

### Provider selection (env)

```env
AI_TEXT_PROVIDER=auto
# auto tries: gemini → groq → openai → mock (first with valid API key wins)

GROQ_API_KEY=gsk_...          # Free: 30 req/min, 14400/day
GEMINI_API_KEY=               # Free tier available
OPENAI_API_KEY=               # Paid — leave empty until needed
```

- Factory in `gateway.py` selects provider based on `AI_TEXT_PROVIDER` and available API keys
- All providers implement the same `TextLLMProvider` interface — swapping is just an env change
- If selected provider key missing → 503 `AI_PROVIDER_NOT_CONFIGURED`

### To switch to paid OpenAI later

1. Set `OPENAI_API_KEY=sk-...` in `.env`
2. Set `AI_TEXT_PROVIDER=openai` (or leave `auto` — it will pick OpenAI if key exists)
3. Restart server. Done. No code changes.

---

## 3. AI CHAT — Two Roles, Two Behaviors

### Routes

- `POST /coach/chat` — non-streaming, returns JSON `{ "reply": "..." }`
- `POST /coach/stream-chat` — SSE streaming, yields text chunks

### Trainer AI (tools + memory)

Flow:
1. Trainer sends message
2. `MemoryService._trainer_chunks()` loads ALL trainer data as RAG context:
   - Trainee roster (names, goals, calories, assigned plans)
   - All workout plans authored by trainer
   - Trainee workout activity (total workouts, duration, last session)
   - Trainer feedback given to each trainee
   - Form reports (exercise scores per trainee)
   - Join requests (pending/accepted/rejected)
   - Coach profile (headline, city, specialties, rating, verified status)
   - Coach reviews, followers, service packages
   - Chat thread summary (total threads, unread)
3. System prompt tells AI it has tools and knows everything
4. `_complete_with_tool_loop()` runs up to **5 rounds**:
   - Calls `complete_with_tools()` with `TRAINER_TOOLS` list
   - If LLM returns `tool_calls` → `ToolExecutor.execute()` runs each tool against real DB
   - Tool results appended to messages → next LLM call
   - Loop ends when LLM returns text content with no tool calls
5. Final text response returned to user

### 10 Trainer Tools

| Tool | What it does | Service method |
|------|-------------|----------------|
| `list_trainees` | List all trainees with names, goals, plans | `TrainerService.list_trainees()` |
| `list_plans` | List all workout plans by trainer | `TrainerService.list_plans()` |
| `create_plan` | Create new plan (title, focus, level, days, exercises) | `TrainerService.create_plan()` |
| `assign_plan` | Assign plan to trainee by IDs | `TrainerService.assign_plan()` |
| `unassign_plan` | Remove trainee's current plan | `TrainerService.unassign_plan()` |
| `send_feedback` | Send feedback message to trainee | `TrainerService.save_feedback()` |
| `list_join_requests` | List pending join requests | `JoinRequestService.list_for_trainer()` |
| `accept_join_request` | Accept a join request → adds trainee to roster | `JoinRequestService.accept()` |
| `reject_join_request` | Reject with optional reason | `JoinRequestService.reject()` |
| `remove_trainee` | Remove trainee from roster | `TrainerService.remove_trainee()` |

The AI chains tools automatically. Example: "Assign my strength plan to Ahmed" → AI calls `list_trainees` → finds Ahmed's ID → calls `list_plans` → finds strength plan ID → calls `assign_plan` with both IDs → confirms in plain language.

### Trainee AI (memory only, NO tools)

Flow:
1. Trainee sends message
2. Memory loads trainee data: assigned plan, workout logs, goals, calories, meals, coach feedback, form reports
3. AI answers using memory context — no actions, just guidance
4. SSE streaming response

Trainee AI handles: "What's my workout today?", "Am I on track?", form tips, nutrition ideas, motivation.

### System prompts

Located in `coach_service.py`:

- `SYSTEM_PROMPT_TRAINER` — tells AI it's a trainer assistant, lists all data it knows, instructs to use tools for actions
- `SYSTEM_PROMPT_TRAINEE` — tells AI it's a trainee coach, use memory context, no tool calling

---

## 4. AI PLAN GENERATION — Solo Trainee

### Route

`POST /coach/programs/generate` — `{ "horizonDays": 7, "notes": "optional" }`

### Behavior

- Loads trainee assessment + exercise catalog
- LLM generates structured JSON plan with real exercise IDs
- Validates IDs against DB; one retry on failure; else 422
- Saves plan with `source: "ai"`, `owner_trainee_id` set
- If trainee has active trainer → **409** `HAS_TRAINER`

### Plan source lock

| Plan type | Created by | Who can edit/delete |
|-----------|-----------|-------------------|
| `source: "ai"` | AI generate | Owning trainee only |
| `source: "trainer"` | Trainer | Owning trainer only |

- `PATCH /trainee/ai-plans/{id}` — trainee edits AI plan (403 `PLAN_LOCKED` if trainer plan)
- `DELETE /trainee/ai-plans/{id}` — trainee deletes AI plan (204) → clears assignment
- `GET /trainee/assigned-plan` returns `source` field so iOS can show/hide edit buttons

---

## 5. FREEMIUM — Quota + Paywall

### Service

`app/services/ai_access.py` — `AiAccessService`

### How it works

| | Free | Subscribed (Apple IAP) |
|---|---|---|
| AI chat | `AI_FREE_CHAT_DAILY_LIMIT` (default 10/day) | Unlimited |
| Weekly tease | `AI_FREE_TEASE_MESSAGES_PER_WEEK` (default 0) | N/A |
| AI plan generation | `AI_FREE_PLAN_GENERATIONS` (default 1 lifetime) | Unlimited regenerate |
| Tool actions | Within chat limit | Unlimited |

### Quota check flow

1. `require_ai_access` dependency on all AI routes
2. Checks `AiEntitlement` table — if active subscription → allow
3. Else checks daily free remaining → if > 0 → allow + consume
4. Else checks weekly tease remaining → if > 0 → allow + consume
5. Else → **402** with `AI_QUOTA_EXCEEDED` or `AI_REQUIRED`

### Error responses

| HTTP | Code | When |
|------|------|------|
| 402 | `AI_QUOTA_EXCEEDED` | Daily/weekly free limit reached |
| 402 | `AI_REQUIRED` | No subscription, no free quota configured |

Response includes `product_hint` (e.g. `"ai.pro.monthly"`) so iOS knows which IAP to show.

### Env config

```env
AI_FREE_CHAT_DAILY_LIMIT=10
AI_FREE_TEASE_MESSAGES_PER_WEEK=0
AI_FREE_PLAN_GENERATIONS=1
```

---

## 6. CAPABILITIES ENDPOINT

### `GET /coach/ai/capabilities`

Authenticated. Returns real config:

```json
{
  "textChat": true,
  "structuredPlanJson": true,
  "weeklySummary": true,
  "visionPose": false,
  "visionFood": false,
  "textProvider": "groq",
  "visionPoseProvider": "stub",
  "visionFoodProvider": "stub",
  "freeChatDailyLimit": 10,
  "freePlanGenerations": 1
}
```

iOS caches this to know what features are live.

---

## 7. VISION STUBS

### `POST /coach/vision/pose` and `POST /coach/vision/food`

While stub providers are active → **501**:

```json
{
  "detail": "Pose AI is not configured yet. Coming soon.",
  "code": "AI_CAPABILITY_UNAVAILABLE",
  "capability": "visionPose"
}
```

When real vision providers are added later, swap stubs in env. No caller rewrites needed.

---

## 8. MEMORY SYSTEM

### Service

`app/services/ai/memory.py` — `MemoryService`

### How it works

- Per-user vector chunks stored in PostgreSQL with pgvector
- `sync_trainer_context()` / `sync_trainee_context()` builds chunks from DB data
- Chunks embedded and stored for cosine similarity retrieval
- On each chat message, relevant chunks retrieved and injected into LLM context

### Trainer chunks include

- Profile (specialty, experience, bio, invite code)
- Full trainee roster (names, goals, calories, assigned plans)
- Workout plans authored + plan assignments
- Trainee workout activity (total workouts, duration, last session)
- Trainer feedback given to each trainee
- Form reports (exercise scores per trainee)
- Join requests (pending/accepted/rejected with messages)
- Coach profile (headline, city, specialties, rating)
- Coach reviews (using `is_hidden` field, not `deleted_at`)
- Coach followers and service packages
- Chat thread summary (total, unread)
- Verification status

### Trainee chunks include

- Assigned plan with exercises
- Workout logs and progress
- Goals, daily calorie target
- Coach feedback received
- Form reports
- Meals and nutrition data

---

## 9. DO NOT BREAK

- `/coach/chat` and `/coach/stream-chat` SSE contract
- Memory sync (`/coach/memory/sync`)
- Trainee assessment
- Plan source lock (source field on workout_plans)
- Boost billing (Stripe)
- Join requests
- Human `/chat/*` (direct messages)
- Notifications
- Existing coach SSE shapes

---

## 10. KEY FILES

| File | Purpose |
|------|---------|
| `app/ai/gateway.py` | Provider factory + `_ChatProviderAdapter` |
| `app/ai/tools.py` | 10 tool definitions + `ToolExecutor` class |
| `app/ai/providers/base.py` | `TextLLMProvider` abstract base |
| `app/ai/providers/text_groq.py` | Groq provider with rate limit retry |
| `app/services/coach_service.py` | `CoachService` — chat, stream, tool loop, system prompts |
| `app/services/ai/memory.py` | `MemoryService` — RAG chunk building + retrieval |
| `app/services/ai_access.py` | `AiAccessService` — freemium quota gate |
| `app/services/ai_program_service.py` | AI plan generation + sanitization |
| `app/services/ai_billing_service.py` | Apple IAP subscription verification |
| `app/api/routers/coach.py` | AI routes with `require_ai_access` dependency |
| `app/core/config.py` | All env vars (AI_FREE_*, API keys, provider selection) |

---

## MANDATORY OUTPUT — Backend Verification Report

When finished, fill in and return this report:

```
## TacTech Backend AI — Verification Report

### A) Provider
- Active text provider: ___
- Provider swappable via env? (YES/NO)
- complete_with_tools() implemented? (YES/NO)
- Groq rate limit retry works? (YES/NO)

### B) Tool Calling
- _complete_with_tool_loop() in CoachService? (YES/NO)
- Max tool rounds: ___
- Tools count: ___
- list_trainees returns real data? (YES/NO)
- create_plan creates in DB? (YES/NO)
- assign_plan assigns? (YES/NO)
- send_feedback saves? (YES/NO)
- accept_join_request works? (YES/NO)
- Multi-step chain works (e.g. list → assign)? (YES/NO)

### C) Memory
- Trainer chunks: roster / plans / logs / feedback / join requests / reviews / profile? (YES/NO)
- Trainee chunks: plan / logs / goals / feedback / meals? (YES/NO)
- CoachReview uses is_hidden (not deleted_at)? (YES/NO)

### D) Roles
- Trainer gets tools? (YES/NO)
- Trainee gets tools? (NO = correct)
- Trainer uses tool loop (non-streaming)? (YES/NO)
- Trainee uses SSE streaming? (YES/NO)

### E) Freemium
- Daily chat limit enforced? (YES/NO) limit: ___
- Plan generation limit enforced? (YES/NO) limit: ___
- Over limit → 402? (YES/NO)
- Subscribed user → unlimited? (YES/NO)

### F) Plan Source
- source field on workout_plans? (YES/NO)
- AI generate sets source=ai? (YES/NO)
- Trainer create sets source=trainer? (YES/NO)
- Trainee cannot edit trainer plan (403)? (YES/NO)
- GET assigned-plan includes source? (YES/NO)

### G) Capabilities
- GET /coach/ai/capabilities returns real config? (YES/NO)
- Vision stubs return 501? (YES/NO)

### H) Files Touched
- (paths)

### I) Manual Tests
1. "List my trainees" → tool call → real data: PASS/FAIL
2. "Create a beginner strength plan" → plan in DB: PASS/FAIL
3. "Assign it to my first trainee" → multi-step chain: PASS/FAIL
4. "How is [trainee] doing?" → memory answer: PASS/FAIL
5. Trainee asks question → no tool call, memory answer: PASS/FAIL
6. Free user hits daily limit → 402: PASS/FAIL
7. Subscribed user → unlimited: PASS/FAIL
8. Solo generate → plan with source=ai: PASS/FAIL
9. Capabilities endpoint returns correct JSON: PASS/FAIL
10. Switch provider via env → works: PASS/FAIL

### J) Gaps
- ___
```
