"""Build and retrieve per-user coach memory vectors via pgvector."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.logging import get_logger
from app.db import models
from app.services.ai.providers import EmbeddingProvider, cosine_similarity

log = get_logger("tactech.memory")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe_score(value: object, default: float = 0.0) -> float:
    """Postgres JSONB rejects NaN/Inf — always store a finite float."""
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(score):
        return default
    return round(score, 4)


def _trim(text: str, limit: int = 900) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class CoachMemoryService:
    def __init__(self, db: Session, settings: Settings, embedder: EmbeddingProvider) -> None:
        self.db = db
        self.settings = settings
        self.embedder = embedder

    async def sync_user(self, user_id: str, role: str) -> int:
        chunks = self._collect_chunks(user_id, role)
        self.db.execute(delete(models.CoachMemoryChunk).where(models.CoachMemoryChunk.user_id == user_id))
        if not chunks:
            self.db.commit()
            return 0
        vectors = await self.embedder.embed([c["content"] for c in chunks])
        dim = self.settings.ai_embedding_dimensions
        now = _utcnow()
        for chunk, vector in zip(chunks, vectors):
            if len(vector) != dim:
                # pad/truncate defensive for local fallback mismatches
                if len(vector) < dim:
                    vector = list(vector) + [0.0] * (dim - len(vector))
                else:
                    vector = list(vector)[:dim]
            self.db.add(
                models.CoachMemoryChunk(
                    id=str(uuid4()),
                    user_id=user_id,
                    source_type=chunk["source_type"],
                    source_id=chunk.get("source_id"),
                    content=chunk["content"],
                    embedding=vector,
                    metadata_json=chunk.get("metadata") or {},
                    updated_at=now,
                )
            )
        self.db.commit()
        return len(chunks)

    async def retrieve(self, user_id: str, query: str, top_k: int | None = None) -> list[dict]:
        top_k = top_k or self.settings.ai_max_context_chunks
        query_vec = (await self.embedder.embed([query]))[0]
        dim = self.settings.ai_embedding_dimensions
        if len(query_vec) != dim:
            if len(query_vec) < dim:
                query_vec = list(query_vec) + [0.0] * (dim - len(query_vec))
            else:
                query_vec = list(query_vec)[:dim]

        try:
            distance = models.CoachMemoryChunk.embedding.cosine_distance(query_vec)
            rows = self.db.execute(
                select(models.CoachMemoryChunk, distance.label("distance"))
                .where(models.CoachMemoryChunk.user_id == user_id)
                .where(models.CoachMemoryChunk.embedding.is_not(None))
                .order_by(distance)
                .limit(top_k)
            ).all()
            results = []
            for row, dist in rows:
                score = _json_safe_score(1.0 - float(dist) if dist is not None else 0.0)
                if score < 0.05 and len(results) >= 3:
                    continue
                results.append(
                    {
                        "id": row.id,
                        "sourceType": row.source_type,
                        "sourceId": row.source_id,
                        "content": row.content,
                        "score": score,
                    }
                )
            return results
        except Exception as exc:
            # Fallback if extension/index missing in some environments
            log.warning("pgvector_retrieve_fallback", error=str(exc)[:200])
            return await self._retrieve_python(user_id, query_vec, top_k)

    async def _retrieve_python(self, user_id: str, query_vec: list[float], top_k: int) -> list[dict]:
        rows = self.db.scalars(
            select(models.CoachMemoryChunk).where(models.CoachMemoryChunk.user_id == user_id)
        ).all()
        scored: list[tuple[float, models.CoachMemoryChunk]] = []
        for row in rows:
            emb = list(row.embedding) if row.embedding is not None else []
            scored.append((_json_safe_score(cosine_similarity(query_vec, emb)), row))
        scored.sort(key=lambda item: item[0], reverse=True)
        results = []
        for score, row in scored[:top_k]:
            if score < 0.05 and len(results) >= 3:
                continue
            results.append(
                {
                    "id": row.id,
                    "sourceType": row.source_type,
                    "sourceId": row.source_id,
                    "content": row.content,
                    "score": score,
                }
            )
        return results

    def _collect_chunks(self, user_id: str, role: str) -> list[dict]:
        user = self.db.get(models.User, user_id)
        if user is None:
            return []
        chunks: list[dict] = [
            {
                "source_type": "profile",
                "source_id": user.id,
                "content": _trim(
                    f"User profile: name={user.name}, role={user.role}, "
                    f"gender={user.gender or 'n/a'}, location={user.location or 'n/a'}, "
                    f"height_cm={user.height_cm or 'n/a'}, weight_kg={user.weight_kg or 'n/a'}, "
                    f"bio={user.bio or 'n/a'}"
                ),
                "metadata": {"kind": "profile"},
            }
        ]
        if role == "trainee" and user.trainee:
            chunks.extend(self._trainee_chunks(user.trainee))
        if role == "trainer" and user.trainer:
            chunks.extend(self._trainer_chunks(user.trainer))
        return chunks

    def _trainee_chunks(self, trainee: models.TraineeProfile) -> list[dict]:
        chunks: list[dict] = [
            {
                "source_type": "trainee_profile",
                "source_id": trainee.id,
                "content": _trim(
                    f"Trainee goals and body metrics: goal={trainee.goal}, "
                    f"height_cm={trainee.height_cm}, weight_kg={trainee.weight_kg}, "
                    f"daily_calorie_target={trainee.daily_calorie_target}, "
                    f"trainer_id={trainee.trainer_id or 'unassigned'}"
                ),
                "metadata": {"kind": "trainee_profile"},
            }
        ]
        if trainee.trainer:
            chunks.append(
                {
                    "source_type": "assigned_trainer",
                    "source_id": trainee.trainer.id,
                    "content": _trim(
                        f"Assigned trainer: specialty={trainee.trainer.specialty}, "
                        f"years={trainee.trainer.years_experience}, bio={trainee.trainer.bio}"
                    ),
                    "metadata": {"kind": "trainer"},
                }
            )

        assessment = self.db.scalars(
            select(models.FitnessAssessment)
            .where(models.FitnessAssessment.trainee_id == trainee.id)
            .order_by(models.FitnessAssessment.created_at.desc())
            .limit(1)
        ).first()
        if assessment:
            chunks.append(
                {
                    "source_type": "fitness_assessment",
                    "source_id": assessment.id,
                    "content": _trim(
                        "Latest fitness assessment intake: "
                        + json.dumps(assessment.payload, default=str)[:700]
                    ),
                    "metadata": {"kind": "assessment"},
                }
            )
            chunks.append(
                {
                    "source_type": "assessment_result",
                    "source_id": assessment.id,
                    "content": _trim(
                        "Assessment coach result: " + json.dumps(assessment.result, default=str)[:700]
                    ),
                    "metadata": {"kind": "assessment_result"},
                }
            )

        assignment = self.db.scalars(
            select(models.PlanAssignment)
            .where(models.PlanAssignment.trainee_id == trainee.id)
            .options(
                joinedload(models.PlanAssignment.plan)
                .joinedload(models.WorkoutPlan.days)
                .joinedload(models.PlanDay.exercises)
            )
            .limit(1)
        ).first()
        if assignment and assignment.plan:
            plan = assignment.plan
            day_bits = []
            for day in (plan.days or [])[:7]:
                ex_names = ", ".join(ex.exercise_id for ex in (day.exercises or [])[:6])
                day_bits.append(
                    f"{day.weekday}:{day.title}/{day.focus}"
                    + (f" [{ex_names}]" if ex_names else "")
                    + (f" notes={day.coach_notes}" if day.coach_notes else "")
                )
            chunks.append(
                {
                    "source_type": "assigned_plan",
                    "source_id": plan.id,
                    "content": _trim(
                        f"Assigned workout plan: title={plan.title}, focus={plan.focus}, "
                        f"level={plan.level}, days_per_week={plan.days_per_week}, "
                        f"notes={plan.notes or 'n/a'}. Schedule: " + " | ".join(day_bits)
                    ),
                    "metadata": {"kind": "plan"},
                }
            )

        logs = self.db.scalars(
            select(models.WorkoutLog)
            .where(models.WorkoutLog.trainee_id == trainee.id)
            .order_by(models.WorkoutLog.completed_at.desc())
            .limit(5)
        ).all()
        for log in logs:
            chunks.append(
                {
                    "source_type": "workout_log",
                    "source_id": log.id,
                    "content": _trim(
                        f"Completed workout on {log.completed_at.isoformat()}: "
                        f"plan={log.plan_id}, duration_min={log.duration_minutes}, "
                        f"sets_logged={len(log.sets or [])}"
                    ),
                    "metadata": {"kind": "log"},
                }
            )

        meals = self.db.scalars(
            select(models.Meal)
            .where(models.Meal.trainee_id == trainee.id)
            .order_by(models.Meal.eaten_at.desc())
            .limit(8)
        ).all()
        if meals:
            safe_lines = [
                f"{m.name} on {m.eaten_at.isoformat()} portion={m.portion_grams}g "
                f"kcal={m.calories} P/C/F={m.protein}/{m.carbs}/{m.fat} source={m.source}"
                for m in meals
            ]
            chunks.append(
                {
                    "source_type": "recent_meals",
                    "source_id": trainee.id,
                    "content": _trim("Recent meals: " + "; ".join(safe_lines)),
                    "metadata": {"kind": "meals"},
                }
            )

        feedback = self.db.scalars(
            select(models.TrainerFeedback)
            .where(models.TrainerFeedback.trainee_id == trainee.id)
            .order_by(models.TrainerFeedback.created_at.desc())
            .limit(5)
        ).all()
        for fb in feedback:
            chunks.append(
                {
                    "source_type": "trainer_feedback",
                    "source_id": fb.id,
                    "content": _trim(f"Trainer feedback ({fb.created_at.date().isoformat()}): {fb.message}"),
                    "metadata": {"kind": "feedback"},
                }
            )

        forms = self.db.scalars(
            select(models.FormReport)
            .where(models.FormReport.trainee_id == trainee.id)
            .order_by(models.FormReport.created_at.desc())
            .limit(5)
        ).all()
        for report in forms:
            chunks.append(
                {
                    "source_type": "form_report",
                    "source_id": report.id,
                    "content": _trim(
                        f"Form report for exercise {report.exercise_id}: score={report.score}, "
                        f"reps={report.rep_count}, cues={', '.join(report.cues or [])}"
                    ),
                    "metadata": {"kind": "form"},
                }
            )
        return chunks

    def _trainer_chunks(self, trainer: models.TrainerProfile) -> list[dict]:
        chunks: list[dict] = [
            {
                "source_type": "trainer_profile",
                "source_id": trainer.id,
                "content": _trim(
                    f"Trainer profile: specialty={trainer.specialty}, "
                    f"years_experience={trainer.years_experience}, bio={trainer.bio}, "
                    f"invite_code={trainer.invite_code}"
                ),
                "metadata": {"kind": "trainer_profile"},
            }
        ]
        assessment = self.db.scalars(
            select(models.TrainerAssessment)
            .where(models.TrainerAssessment.trainer_id == trainer.id)
            .order_by(models.TrainerAssessment.created_at.desc())
            .limit(1)
        ).first()
        if assessment:
            chunks.append(
                {
                    "source_type": "trainer_assessment",
                    "source_id": assessment.id,
                    "content": _trim(
                        "Trainer coaching assessment: " + json.dumps(assessment.payload, default=str)[:800]
                    ),
                    "metadata": {"kind": "trainer_assessment"},
                }
            )

        trainees = self.db.scalars(
            select(models.TraineeProfile)
            .where(models.TraineeProfile.trainer_id == trainer.id)
            .options(joinedload(models.TraineeProfile.user))
            .limit(25)
        ).all()
        if trainees:
            roster = []
            for t in trainees:
                name = t.user.name if t.user else t.id
                roster.append(f"{name} goal={t.goal} kcal={t.daily_calorie_target}")
            chunks.append(
                {
                    "source_type": "trainee_roster",
                    "source_id": trainer.id,
                    "content": _trim("Active trainees: " + "; ".join(roster)),
                    "metadata": {"kind": "roster"},
                }
            )

        plans = self.db.scalars(
            select(models.WorkoutPlan)
            .where(models.WorkoutPlan.trainer_id == trainer.id, models.WorkoutPlan.deleted_at.is_(None))
            .order_by(models.WorkoutPlan.title.asc())
            .limit(10)
        ).all()
        for plan in plans:
            chunks.append(
                {
                    "source_type": "trainer_plan",
                    "source_id": plan.id,
                    "content": _trim(
                        f"Plan authored: {plan.title} focus={plan.focus} level={plan.level} "
                        f"days/wk={plan.days_per_week} notes={plan.notes or 'n/a'}"
                    ),
                    "metadata": {"kind": "plan"},
                }
            )
        return chunks
