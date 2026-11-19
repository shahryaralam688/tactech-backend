# TacTech iOS — AI Features Implementation Prompt

You are a senior SwiftUI engineer on **TacTech Trainer iOS**.

**Auth:** Bearer JWT · **JSON:** camelCase · **Errors:** `{ "detail": "…", "code": "…" }`

---

## 1. WHAT THE APP DOES

TacTech has two user types:

- **Trainer**: manages trainees, creates plans, gives feedback — AI automates all of this through chat
- **Trainee**: follows plans, logs workouts, asks AI for guidance — AI knows their plan, progress, goals

The AI is the **core paid feature**. Everything else (linking, plans, chat) is free. AI chat + AI plan generation drive the subscription.

---

## 2. AI CHAT (already exists — verify + enhance)

### How it works

- `POST /coach/chat` (non-streaming) and `POST /coach/stream-chat` (SSE streaming)
- Trainer sends a message → backend AI reads ALL trainer data (trainees, plans, progress, join requests, reviews) → AI can take real actions (create plan, assign plan, send feedback, accept join request) → returns text response
- Trainee sends a message → backend AI reads trainee data (plan, logs, goals, feedback) → returns guidance
- **Tool calling is 100% backend** — the frontend just sends messages and receives text responses. No tool logic on iOS.

### What to do

1. **Chat UI stays the same** — no contract changes. AI responses may take 1-3 extra seconds when the AI runs actions. Existing timeouts are fine.

2. **Update suggested prompts** to showcase what the AI can actually do:

```swift
// Trainer suggestions
[
    "List all my trainees",
    "Create a beginner strength plan",
    "Show pending join requests",
    "How is my trainee doing?"
]

// Trainee suggestions
[
    "What's my workout today?",
    "Am I on track this week?",
    "Give me form tips",
    "Nutrition ideas for my goal"
]
```

3. **Refresh data after AI chat** — When the user leaves the AI chat screen, the AI may have created a plan, assigned a plan, accepted a join request, or sent feedback. Trigger a refresh on these screens when returning from AI chat:
   - Trainee list (new trainee from accepted join request)
   - Plans list (new plan created by AI)
   - Assigned plan (plan assigned/unassigned by AI)

   Implementation: `onAppear` reload or a notification posted when AI chat closes.

---

## 3. AI FREEMIUM + PAYWALL

### Backend behavior

| | Free | Subscribed (Apple IAP) |
|---|---|---|
| AI chat | 10 messages/day | Unlimited |
| AI plan generation | 1 lifetime | Unlimited |
| Over limit | 402 response | N/A |

### API responses to handle

| HTTP | Code | Meaning | iOS action |
|------|------|---------|------------|
| 402 | `AI_QUOTA_EXCEEDED` | Daily chat limit reached | Show AI paywall / upgrade sheet |
| 402 | `AI_REQUIRED` | No subscription, no free left | Show AI paywall / upgrade sheet |

### Capabilities endpoint

`GET /coach/ai/capabilities` — call once, cache:

```json
{
  "textChat": true,
  "structuredPlanJson": true,
  "weeklySummary": true,
  "visionPose": false,
  "visionFood": false,
  "textProvider": "groq",
  "freeChatDailyLimit": 10,
  "freePlanGenerations": 1
}
```

### UX rules

- 402 on chat → show paywall with "Upgrade to continue chatting"
- 402 on plan generate → show paywall with "Upgrade to regenerate plans"
- Optional: show remaining free messages counter in chat UI (calculate from capabilities limit minus used)

---

## 4. SOLO TRAINEE — "Generate My Week"

When trainee has **no linked trainer**:

### Step 1 — Show Assessment Review Screen FIRST

Before generating any workout, ALWAYS show the trainee their current assessment data so they can review and change it. Fetch from `GET /trainee/assessment`.

Show an editable form/card with these fields pre-filled from their assessment:

| Field | Source | Editable? |
|-------|--------|-----------|
| Goal | `goal` (e.g. "Muscle gain", "Weight loss", "Stay fit") | YES — picker |
| Gender | `gender` | YES — picker |
| Weight (kg) | `weightKg` | YES — number input |
| Age | `age` | YES — number input |
| Fitness level (1-10) | `fitnessLevel` | YES — slider |
| Experience | `hasExperience` (true/false) | YES — toggle |
| Days per week | `daysPerWeek` (1-7) | YES — stepper |
| Limitations | `limitations` (e.g. ["bad knee", "lower back"]) | YES — multi-select/tags |
| Diet | `diet` (e.g. "balanced", "high protein", "vegetarian") | YES — picker |
| Exercise preferences | `exercisePreferences` (e.g. ["compound", "dumbbell"]) | YES — multi-select |
| Calorie goal | `calorieGoal` | YES — number input |
| Concerns | `concerns` (free text) | YES — text field |

**Bottom of card:** Two buttons:
- **"Update & Generate"** — if user changed anything, first `POST /trainee/assessment` with updated data, then `POST /coach/programs/generate`
- **"Generate with current"** — skip update, go straight to `POST /coach/programs/generate`

### Step 2 — Generate workout

- `POST /coach/programs/generate` with `{ "horizonDays": 7, "notes": "optional" }`
- Show loading state: "AI is building your plan..."
- Backend uses the assessment data (including any changes from Step 1) to generate a personalized workout plan
- Handle errors:
  - 402 → paywall (free generation used)
  - 409 `HAS_TRAINER` → toast "You have a trainer — use their plan"
  - 422 → toast "Could not generate plan, try again"

### Step 3 — Show generated plan

- Display the generated plan with days, exercises, sets, reps
- Trainee can edit (it's `source: "ai"`) or delete and regenerate

### No assessment yet?

If `GET /trainee/assessment` returns `null` / 404 — show the full assessment form (all fields empty) and require submission before generating. The trainee must complete assessment first.

When trainee **has a linked trainer**: hide generate card, show trainer's assigned plan.

---

## 5. PLAN SOURCE LOCK

### Model

Extend `WorkoutPlan` with:

```swift
var source: String?  // "ai" | "trainer"
```

Decode safely. If missing: treat as `"trainer"` if `trainerId` is non-empty, else `"ai"`.

### UX rules

| Plan source | Edit/Delete visible? | Label |
|-------------|---------------------|-------|
| `source == "ai"` | YES — trainee can edit/delete | "AI Generated Plan" |
| `source == "trainer"` | NO — read only | "Assigned by your trainer" |

### API

- Edit AI plan: `PATCH /trainee/ai-plans/{id}`
- Delete AI plan: `DELETE /trainee/ai-plans/{id}` (returns 204)
- 403 `PLAN_LOCKED` → toast with server `detail` message
- After deleting AI plan → clear local assignment → show "Generate my week" card again

Trainer side: keep existing edit/delete for their own plans. No changes.

---

## 6. VISION PLACEHOLDERS

If capabilities `visionPose` or `visionFood` are `false`:

- Show "Advanced · Coming soon" label
- Do not crash on 501/503 with `AI_CAPABILITY_UNAVAILABLE`
- No camera/upload UI for these features until capability is `true`

---

## 7. DO NOT BREAK

- Boost billing (Stripe checkout)
- Join requests (send/accept/reject)
- Human chat (direct messages between trainer and trainee)
- Form Studio
- Trainer plan create/assign/unassign
- Assessment flow
- Existing AI chat SSE streaming

---

## 8. DO NOT

- Add any tool-calling logic on iOS — it's 100% backend
- Change the chat API contract (`/coach/chat`, `/coach/stream-chat`)
- Add new AI endpoints — everything uses existing routes
- Let trainee edit/delete trainer plans
- Remove any existing feature

---

## MANDATORY OUTPUT — iOS Verification Report

When finished, fill in and return this report:

```
## TacTech iOS AI — Verification Report

### A) AI Chat
- Chat works with tool-calling responses (longer replies)? (YES/NO)
- SSE streaming preserved? (YES/NO)
- Trainer suggested prompts updated? (YES/NO)
- Trainee suggested prompts updated? (YES/NO)
- Data refresh after leaving chat? (YES/NO)

### B) Freemium
- Fetches /coach/ai/capabilities? (YES/NO)
- Cached where: ___
- 402 AI_QUOTA_EXCEEDED → paywall? (YES/NO)
- 402 AI_REQUIRED → paywall? (YES/NO)

### C) Solo Generate
- "Generate my week" when no trainer? (YES/NO)
- POST /coach/programs/generate? (YES/NO)
- 402 → paywall? (YES/NO)
- 409 HAS_TRAINER → toast? (YES/NO)

### D) Plan Source Lock
- source decoded on WorkoutPlan? (YES/NO)
- Missing source fallback rule: ___
- AI plan → Edit/Delete visible? (YES/NO)
- Trainer plan → Edit/Delete hidden? (YES/NO)
- Delete AI plan → generate card returns? (YES/NO)
- 403 PLAN_LOCKED → toast? (YES/NO)

### E) Vision Placeholders
- Pose "Coming soon" if false? (YES/NO)
- Food "Coming soon" if false? (YES/NO)

### F) Features Preserved
- Boost? (YES/NO)
- Join requests? (YES/NO)
- Human chat? (YES/NO)
- Form Studio? (YES/NO)
- Trainer plan CRUD? (YES/NO)
- Assessment? (YES/NO)

### G) Files Touched
- (paths)

### H) Manual QA
1. Trainer "list my trainees" → real data back: PASS/FAIL
2. Trainer "create a plan" → plan in plans list: PASS/FAIL
3. Trainee "what's my workout" → guidance: PASS/FAIL
4. Chat until daily limit → paywall: PASS/FAIL
5. Solo generate → plan appears: PASS/FAIL
6. Second generate → paywall: PASS/FAIL
7. AI plan edit/delete works: PASS/FAIL
8. Trainer plan read-only: PASS/FAIL
9. Pose/food coming soon: PASS/FAIL
10. Boost/join/human chat still work: PASS/FAIL

### I) Gaps
- ___
```
