"""Solo AI structured plan generation via the AI Gateway."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import AiGateway
from app.ai.schemas.workout_plan_out import LlmWorkoutPlan
from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.repositories.assignment import AssignmentRepository
from app.repositories.exercise import ExerciseRepository
from app.repositories.plan import PlanRepository
from app.repositories.roster_link import RosterLinkRepository
from app.repositories.trainee import TraineeRepository
from app.schemas.mappers import plan_out
from app.services.ai_access import AiAccessService

if TYPE_CHECKING:
    from app.api.deps import Principal

log = get_logger("tactech.ai.program")

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_DEFAULT_REPS = 10
_DEFAULT_SETS = 3
_DEFAULT_REST = 60
_DEFAULT_DURATION = 30
_MAX_DURATION = 120

# Prefer these catalog staples when remapping unknown ids
_SAFE_DEFAULT_PREF = (
    "ex-squat",
    "ex-pushup",
    "ex-plank",
    "ex-lunge",
    "ex-row",
    "ex-ai-glute-br",
    "ex-ai-bird-dog",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Grab outermost object if model adds prose
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def _as_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) >= 2}


def _safe_default_id(valid_ids: set[str]) -> str:
    for pref in _SAFE_DEFAULT_PREF:
        if pref in valid_ids:
            return pref
    return next(iter(valid_ids))


def _fuzzy_map_exercise_id(
    bad_id: str,
    *,
    valid_ids: set[str],
    id_to_name: dict[str, str],
) -> str:
    """Map invented ids like ex-bird-dog → ex-ai-bird-dog via token / name similarity."""
    if bad_id in valid_ids:
        return bad_id

    bad_tokens = _tokens(bad_id.replace("ex-", "").replace("ex_ai_", "").replace("ex-ai-", ""))
    best_id = ""
    best_score = 0.0

    for eid in valid_ids:
        name = id_to_name.get(eid, "")
        eid_tokens = _tokens(eid.replace("ex-ai-", "").replace("ex-", ""))
        name_tokens = _tokens(name)
        overlap = 0.0
        if bad_tokens:
            union = bad_tokens | eid_tokens | name_tokens
            inter = bad_tokens & (eid_tokens | name_tokens)
            overlap = len(inter) / max(1, len(union))
        seq = max(
            SequenceMatcher(None, bad_id.lower(), eid.lower()).ratio(),
            SequenceMatcher(None, " ".join(sorted(bad_tokens)), name.lower()).ratio() if bad_tokens else 0.0,
        )
        score = max(overlap * 1.2, seq)
        # Strong boost when all significant bad tokens appear in catalog id/name
        if bad_tokens and bad_tokens <= (eid_tokens | name_tokens):
            score = max(score, 0.85)
        if score > best_score:
            best_score = score
            best_id = eid

    if best_id and best_score >= 0.45:
        return best_id
    return _safe_default_id(valid_ids)


def sanitize_llm_plan_dict(
    data: dict[str, Any],
    *,
    valid_ids: set[str],
    id_to_name: dict[str, str],
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    """Normalize / clamp / remap LLM JSON before strict Pydantic validate.

    Returns (cleaned_dict_or_None, stats).
    """
    stats = {
        "repsClamped": 0,
        "setsClamped": 0,
        "restClamped": 0,
        "durationClamped": 0,
        "daysDropped": 0,
        "idsRemapped": 0,
    }
    if not isinstance(data, dict):
        return None, stats

    raw_days = data.get("days")
    if not isinstance(raw_days, list):
        raw_days = []

    clean_days: list[dict[str, Any]] = []
    for entry in raw_days:
        if not isinstance(entry, dict):
            stats["daysDropped"] += 1
            continue
        exercises_in = entry.get("exercises")
        if not isinstance(exercises_in, list):
            exercises_in = []

        clean_exercises: list[dict[str, Any]] = []
        for item in exercises_in:
            if not isinstance(item, dict):
                continue
            eid = str(
                item.get("exerciseId")
                or item.get("exercise_id")
                or item.get("id")
                or ""
            ).strip()
            if not eid:
                continue
            if eid not in valid_ids:
                mapped = _fuzzy_map_exercise_id(eid, valid_ids=valid_ids, id_to_name=id_to_name)
                log.info("ai_plan_id_remapped", **{"from": eid, "to": mapped})
                eid = mapped
                stats["idsRemapped"] += 1

            reps = _as_int(item.get("reps"), _DEFAULT_REPS)
            if reps < 1:
                reps = _DEFAULT_REPS
                stats["repsClamped"] += 1
            reps = min(100, reps)

            sets = _as_int(item.get("sets"), _DEFAULT_SETS)
            if sets < 1:
                sets = _DEFAULT_SETS
                stats["setsClamped"] += 1
            sets = min(20, sets)

            rest = _as_int(item.get("restSeconds", item.get("rest_seconds")), _DEFAULT_REST)
            if rest < 0:
                rest = _DEFAULT_REST
                stats["restClamped"] += 1
            rest = min(600, rest)

            weight = item.get("recommendedWeightKg", item.get("recommended_weight_kg"))
            try:
                weight_f = float(weight) if weight is not None and weight != "" else None
            except (TypeError, ValueError):
                weight_f = None

            clean_exercises.append(
                {
                    "exerciseId": eid,
                    "sets": sets,
                    "reps": reps,
                    "restSeconds": rest,
                    "recommendedWeightKg": weight_f,
                    "notes": item.get("notes"),
                }
            )

        if not clean_exercises:
            # Keep rest-style days only if weekday present? Prefer drop empty training days.
            stats["daysDropped"] += 1
            continue

        weekday = str(entry.get("weekday") or entry.get("day") or "Mon").strip()
        wd = weekday.title()[:3]
        if wd not in _WEEKDAYS:
            wd = "Mon"

        day_dur = _as_int(
            entry.get("durationMinutes", entry.get("duration_minutes")),
            _DEFAULT_DURATION,
        )
        if day_dur < 10:
            day_dur = _DEFAULT_DURATION
            stats["durationClamped"] += 1
        day_dur = min(_MAX_DURATION, day_dur)

        clean_days.append(
            {
                "weekday": wd,
                "title": str(entry.get("title") or f"{wd} session"),
                "focus": str(entry.get("focus") or data.get("focus") or "Training"),
                "durationMinutes": day_dur,
                "warmup": entry.get("warmup"),
                "cooldown": entry.get("cooldown"),
                "coachNotes": entry.get("coachNotes", entry.get("coach_notes")),
                "exercises": clean_exercises,
            }
        )

    if not clean_days:
        return None, stats

    plan_dur = _as_int(
        data.get("durationMinutes", data.get("duration_minutes")),
        _DEFAULT_DURATION,
    )
    if plan_dur < 10:
        plan_dur = _DEFAULT_DURATION
        stats["durationClamped"] += 1
    plan_dur = min(_MAX_DURATION, max(plan_dur, max(d["durationMinutes"] for d in clean_days)))

    dpw = _as_int(data.get("daysPerWeek", data.get("days_per_week")), len(clean_days))
    dpw = max(1, min(7, dpw if dpw > 0 else len(clean_days)))
    dpw = min(dpw, len(clean_days)) or len(clean_days)

    title = str(data.get("title") or "AI Solo Week").strip() or "AI Solo Week"
    focus = str(data.get("focus") or "General Fitness").strip() or "General Fitness"
    level = str(data.get("level") or "Beginner").strip() or "Beginner"

    cleaned = {
        "title": title,
        "focus": focus,
        "durationMinutes": plan_dur,
        "level": level,
        "daysPerWeek": dpw,
        "notes": data.get("notes"),
        "days": clean_days,
    }
    if any(stats.values()):
        log.info("ai_plan_sanitize_applied", **stats)
    return cleaned, stats


class AiProgramService:
    def __init__(self, db: Session, settings: Settings, gateway: AiGateway | None = None) -> None:
        self.db = db
        self.settings = settings
        self.gateway = gateway or AiGateway(settings)
        self.access = AiAccessService(db, settings)
        self.trainees = TraineeRepository(db)
        self.exercises = ExerciseRepository(db)
        self.plans = PlanRepository(db)
        self.assignments = AssignmentRepository(db)
        self.links = RosterLinkRepository(db)

    async def generate(
        self,
        principal: Principal,
        *,
        horizon_days: int = 7,
        notes: str | None = None,
    ):
        if principal.role != "trainee" or not principal.trainee_id:
            raise ValidationAppError("Only trainees can generate a solo AI plan.")

        trainee = self.trainees.get(principal.trainee_id)
        if trainee is None:
            raise NotFoundError("Trainee profile not found.")

        active = self.links.get_active_for_trainee(trainee.id)
        if active is not None or trainee.trainer_id:
            raise ConflictError(
                "You already have a trainer. Use their assigned plan instead of solo AI generate.",
                code="HAS_TRAINER",
            )

        self.access.assert_plan_generate_access(principal.user_id)

        catalog = self.exercises.list_all(active_only=True)
        if not catalog:
            raise ValidationAppError(
                "Could not build a valid workout plan. Try again.",
                status_code=422,
                code="AI_PLAN_INVALID",
            )

        valid_ids = {ex.id for ex in catalog}
        id_to_name = {ex.id: ex.name for ex in catalog}
        catalog_lines = [f"{ex.id}|{ex.name}" for ex in catalog[:80]]

        assessment = self.db.scalars(
            select(models.FitnessAssessment)
            .where(models.FitnessAssessment.trainee_id == trainee.id)
            .order_by(models.FitnessAssessment.created_at.desc())
            .limit(1)
        ).first()
        assessment_blob = assessment.payload if assessment else {}
        goal = (
            trainee.goal
            or (assessment_blob.get("goal") if isinstance(assessment_blob, dict) else None)
            or "general fitness"
        )

        horizon = max(1, min(int(horizon_days or 7), 14))
        system = (
            "You are TacTech programming engine. Return ONLY valid JSON (no markdown) matching:\n"
            '{"title":str,"focus":str,"durationMinutes":int,"level":str,"daysPerWeek":int,'
            '"notes":str|null,"days":[{"weekday":"Mon|Tue|Wed|Thu|Fri|Sat|Sun","title":str,'
            '"focus":str,"durationMinutes":int,"warmup":str|null,"cooldown":str|null,'
            '"coachNotes":str|null,"exercises":[{"exerciseId":str,"sets":int,"reps":int,'
            '"restSeconds":int,"recommendedWeightKg":number|null,"notes":str|null}]}]}\n'
            "HARD RULES:\n"
            "- days MUST be an array of objects (never empty strings, never null entries).\n"
            "- Every exercise.reps >= 1 and sets >= 1.\n"
            "- durationMinutes >= 10 (plan and each day).\n"
            "- Prefer 3–5 training days; each day 3–8 exercises.\n"
            "- exerciseId MUST be exactly one of the catalog ids below.\n"
            f"VALID_EXERCISE_IDS: {','.join(sorted(valid_ids)[:80])}\n"
            f"CATALOG (id|name):\n" + "\n".join(catalog_lines)
        )
        user_msg = (
            f"Generate a {horizon}-day horizon workout plan.\n"
            f"Trainee goal: {goal}\n"
            f"Assessment: {json.dumps(assessment_blob)[:1500]}\n"
            f"Notes: {(notes or '').strip() or 'none'}"
        )

        plan_model = await self._llm_plan_with_retry(system, user_msg, valid_ids, id_to_name)
        plan = self._persist(trainee, plan_model)
        assignment = models.PlanAssignment(
            id=str(uuid4()),
            plan_id=plan.id,
            trainee_id=trainee.id,
            assigned_at=_utcnow(),
        )
        self.assignments.replace(assignment)
        self.access.consume_plan_generation(principal.user_id)
        self.db.commit()
        self.db.refresh(plan)
        return plan_out(plan)

    async def weekly_summary(self, principal: Principal) -> dict[str, Any]:
        """Thin text summary of recent logs. Free users: allowed if chat quota ok (caller gates)."""
        self.access.assert_ai_access(principal.user_id, consume_tease=True)

        trainee_id = principal.trainee_id
        logs: list[models.WorkoutLog] = []
        if trainee_id:
            logs = list(
                self.db.scalars(
                    select(models.WorkoutLog)
                    .where(models.WorkoutLog.trainee_id == trainee_id)
                    .order_by(models.WorkoutLog.completed_at.desc())
                    .limit(20)
                ).all()
            )
        log_blob = [
            {
                "planId": row.plan_id,
                "completedAt": row.completed_at.isoformat() if row.completed_at else None,
                "durationMinutes": row.duration_minutes,
            }
            for row in logs
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are TacTech AI. Write a short weekly training summary (4–8 sentences) "
                    "for the athlete. Be encouraging and specific. No medical claims."
                ),
            },
            {
                "role": "user",
                "content": f"Recent workout logs (JSON): {json.dumps(log_blob)[:3000]}",
            },
        ]
        text = await self.gateway.complete_text(messages, max_tokens=500)
        return {"summary": text, "logCount": len(logs)}

    async def _llm_plan_with_retry(
        self,
        system: str,
        user_msg: str,
        valid_ids: set[str],
        id_to_name: dict[str, str],
    ) -> LlmWorkoutPlan:
        last_error: str | None = None
        for attempt in range(2):
            retry_hint = ""
            if attempt == 1 and last_error:
                retry_hint = (
                    f"\nFIX previous errors: {last_error}. "
                    "reps must be >= 1, sets >= 1, durationMinutes >= 10, "
                    "days must be objects only, exerciseId must be from VALID_EXERCISE_IDS."
                )
            raw = await self.gateway.complete_text(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg + retry_hint},
                ],
                temperature=0.35,
                max_tokens=2500,
                response_json=True,
            )
            try:
                data = _extract_json(raw)
            except Exception as exc:
                last_error = f"invalid JSON: {exc}"
                log.warning("ai_plan_parse_failed", attempt=attempt, error=last_error)
                continue

            cleaned, _stats = sanitize_llm_plan_dict(
                data, valid_ids=valid_ids, id_to_name=id_to_name
            )
            if cleaned is None:
                last_error = "no valid days after sanitize"
                log.warning("ai_plan_parse_failed", attempt=attempt, error=last_error)
                continue

            try:
                plan = LlmWorkoutPlan.model_validate(cleaned)
            except Exception as exc:
                last_error = f"schema after sanitize: {exc}"
                log.warning("ai_plan_parse_failed", attempt=attempt, error=last_error)
                continue

            if not plan.days or not any(d.exercises for d in plan.days):
                last_error = "empty days/exercises after sanitize"
                log.warning("ai_plan_parse_failed", attempt=attempt, error=last_error)
                continue

            # Final safety: remap any straggler ids
            for day in plan.days:
                for ex in day.exercises:
                    if ex.exercise_id not in valid_ids:
                        mapped = _fuzzy_map_exercise_id(
                            ex.exercise_id, valid_ids=valid_ids, id_to_name=id_to_name
                        )
                        log.info(
                            "ai_plan_id_remapped",
                            **{"from": ex.exercise_id, "to": mapped},
                        )
                        ex.exercise_id = mapped
            return plan

        raise ValidationAppError(
            "Could not build a valid workout plan. Try again.",
            status_code=422,
            code="AI_PLAN_INVALID",
        )

    def _persist(self, trainee: models.TraineeProfile, plan_model: LlmWorkoutPlan) -> models.WorkoutPlan:
        days: list[models.PlanDay] = []
        flat: list[models.WorkoutExercise] = []
        for day_index, day in enumerate(plan_model.days):
            day_exercises: list[models.PlanExercise] = []
            for ex_index, item in enumerate(day.exercises):
                day_exercises.append(
                    models.PlanExercise(
                        id=str(uuid4()),
                        exercise_id=item.exercise_id,
                        sort_order=ex_index,
                        sets=item.sets,
                        reps=item.reps,
                        rest_seconds=item.rest_seconds,
                        recommended_weight_kg=item.recommended_weight_kg,
                        tempo=None,
                        rpe=None,
                        notes=item.notes,
                        side=None,
                        prescribed_sets=[],
                    )
                )
                flat.append(
                    models.WorkoutExercise(
                        id=str(uuid4()),
                        exercise_id=item.exercise_id,
                        sets=item.sets,
                        reps=item.reps,
                        rest_seconds=item.rest_seconds,
                        recommended_weight_kg=item.recommended_weight_kg,
                        sort_order=len(flat),
                    )
                )
            days.append(
                models.PlanDay(
                    id=str(uuid4()),
                    weekday=day.weekday,
                    start_time=None,
                    title=day.title or f"{day.weekday} session",
                    focus=day.focus or plan_model.focus,
                    duration_minutes=day.duration_minutes or plan_model.duration_minutes,
                    location=None,
                    warmup=day.warmup,
                    cooldown=day.cooldown,
                    coach_notes=day.coach_notes,
                    sort_order=day_index,
                    exercises=day_exercises,
                )
            )

        plan = models.WorkoutPlan(
            id=str(uuid4()),
            trainer_id=None,
            source="ai",
            owner_trainee_id=trainee.id,
            title=plan_model.title,
            focus=plan_model.focus,
            duration_minutes=plan_model.duration_minutes,
            level=plan_model.level,
            days_per_week=plan_model.days_per_week or len(days),
            notes=plan_model.notes,
            exercises=flat,
            days=days,
        )
        self.plans.add(plan)
        return plan
