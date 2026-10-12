# Sandow Score — live Profile series

Honest time-series for the Profile chart. **No random / seeded placeholder scores.**

```http
GET /me/sandow-score?period=week|month
Authorization: Bearer <JWT>
```

- **Timezone:** UTC calendar days  
- **Empty days:** always included with `score: 0` (client does not need to zero-fill)  
- **week:** last 7 UTC days including today  
- **month:** last 30 UTC days including today  
- **summaryScore:** round(mean of daily scores where `score > 0`); `0` if none  

## Modes

| Role | Boost active *now*? | `mode` | Source |
|------|---------------------|--------|--------|
| trainee | n/a | `workout_performance` | Own form reports + workout logs |
| trainer | yes | `boost_analytics` | Phase 6 `coach_profile_events` |
| trainer | no | `roster_performance` | Linked trainees (`trainer_id`) |

Phase 6 `/me/coach-analytics` is unchanged.

## Formulas (stable)

### Trainee day

1. Form report(s) that UTC day → `round(avg(score))` clamped 0–100  
2. Else workout log(s) → `min(100, 70 + 8 * logCount)`  
3. Else → `0`

### Boost day

```
raw = views + 5*contacts + 0.25*impressions
score = round(100 * raw / max_raw_in_period)   # 0 if period max is 0
```

Points also include `views`, `contacts`, `impressions`.

### Roster day

For each linked trainee, compute the trainee daily score, then  
`score = round(mean across roster)` (empty roster → 0).  
Also: `activeTrainees` (trainees with score > 0), `sessionsLogged` (workout log count).

## iOS precedence for chart

1. Call `GET /me/sandow-score?period=week` (or `month`) after login / pull-to-refresh  
2. Plot `points[].score` vs `points[].label` (or `date`)  
3. Header: `summaryScore` + `summaryLabel`  
4. Title/subtitle come from the payload (`mode` drives copy)  

## Example — trainee

```json
{
  "role": "trainee",
  "mode": "workout_performance",
  "period": "week",
  "title": "Sandow Score",
  "subtitle": "Workout & form",
  "from": "2026-10-06",
  "to": "2026-10-12",
  "summaryScore": 84,
  "summaryLabel": "This week",
  "points": [
    { "date": "2026-10-06", "label": "Mon", "score": 0 },
    { "date": "2026-10-07", "label": "Tue", "score": 82 },
    { "date": "2026-10-12", "label": "Sun", "score": 87 }
  ]
}
```

## Example — trainer + Boost

```json
{
  "role": "trainer",
  "mode": "boost_analytics",
  "period": "week",
  "title": "Boost reach",
  "subtitle": "Profile views & contacts",
  "boostActive": true,
  "from": "2026-10-06",
  "to": "2026-10-12",
  "summaryScore": 72,
  "summaryLabel": "This week",
  "points": [
    {
      "date": "2026-10-06",
      "label": "Mon",
      "score": 65,
      "views": 12,
      "contacts": 2,
      "impressions": 40
    }
  ]
}
```

## Example — trainer free (roster)

```json
{
  "role": "trainer",
  "mode": "roster_performance",
  "period": "week",
  "title": "Clients performance",
  "subtitle": "Average trainee activity",
  "boostActive": false,
  "traineeCount": 6,
  "from": "2026-10-06",
  "to": "2026-10-12",
  "summaryScore": 78,
  "summaryLabel": "This week",
  "points": [
    {
      "date": "2026-10-06",
      "label": "Mon",
      "score": 74,
      "activeTrainees": 3,
      "sessionsLogged": 5
    }
  ]
}
```

## Errors

| HTTP | code | when |
|------|------|------|
| 400 | VALIDATION_ERROR | bad `period` |
| 401 | UNAUTHORIZED | no/invalid JWT |
| 403 | FORBIDDEN | missing trainee/trainer profile |
