"""AI coach tool definitions and executor for trainer actions."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.db import models
from app.schemas.join_requests import RejectJoinRequest
from app.schemas.requests import (
    AssignPlanRequest,
    CreateFeedbackRequest,
    CreatePlanRequest,
    PlanDayExerciseIn,
    PlanDayIn,
)
from app.repositories.assignment import AssignmentRepository
from app.services.join_request_service import JoinRequestService
from app.services.trainer_service import TrainerService

log = get_logger("tactech.ai.tools")

# Argument limits enforced inside the executor only — REST API and app are unaffected.
_FEEDBACK_MAX_MSG = 2000
_PLAN_MAX_TITLE = 120
_PLAN_MAX_FOCUS = 120
_PLAN_MAX_NOTES = 1000
_PLAN_MAX_DAYS = 7
_PLAN_MAX_EXERCISES_PER_DAY = 15
_PLAN_MAX_SETS_PER_EXERCISE = 10

# Tools intentionally withheld from the model — require a human confirmation
# step before they can be re-enabled.  Referenced here so they can be found
# and enabled in a future confirmation-gate feature.
_DESTRUCTIVE_TOOLS_DISABLED: list[str] = [
    "remove_trainee",
    "reject_join_request",
    "unassign_plan",
]

TRAINER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_trainees",
            "description": "List all trainees currently assigned to this trainer with their names, goals, and calorie targets.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_plans",
            "description": "List all workout plans created by this trainer.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Create a new workout plan. Days array is optional for simple plans.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Plan name"},
                    "focus": {"type": "string", "description": "e.g. Strength, Cardio, Full Body"},
                    "duration_minutes": {"type": "integer", "description": "Workout duration in minutes"},
                    "level": {"type": "string", "enum": ["Beginner", "Intermediate", "Advanced"]},
                    "days_per_week": {"type": "integer", "minimum": 1, "maximum": 7},
                    "notes": {"type": "string", "description": "Optional coach notes"},
                    "days": {
                        "type": "array",
                        "description": "Optional structured days with exercises",
                        "items": {
                            "type": "object",
                            "properties": {
                                "weekday": {"type": "string"},
                                "title": {"type": "string"},
                                "focus": {"type": "string"},
                                "duration_minutes": {"type": "integer"},
                                "exercises": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "exercise_id": {"type": "string"},
                                            "sets": {"type": "integer"},
                                            "reps": {"type": "integer"},
                                            "rest_seconds": {"type": "integer"},
                                        },
                                        "required": ["exercise_id", "sets", "reps"],
                                    },
                                },
                            },
                            "required": ["weekday", "title", "focus"],
                        },
                    },
                },
                "required": ["title", "focus", "duration_minutes", "level", "days_per_week"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_plan",
            "description": "Assign a workout plan to a trainee. Use list_trainees and list_plans first to get IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string", "description": "The workout plan ID"},
                    "trainee_id": {"type": "string", "description": "The trainee profile ID"},
                },
                "required": ["plan_id", "trainee_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_feedback",
            "description": "Send coaching feedback to a trainee.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trainee_id": {"type": "string", "description": "The trainee profile ID"},
                    "message": {"type": "string", "description": "Feedback message"},
                    "related_exercise_id": {"type": "string", "description": "Optional exercise ID the feedback relates to"},
                },
                "required": ["trainee_id", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_join_requests",
            "description": "List pending join requests from trainees wanting to join this trainer.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "accept_join_request",
            "description": "Accept a trainee's join request, adding them to the roster.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "The join request ID"},
                },
                "required": ["request_id"],
            },
        },
    },
]


class ToolExecutor:
    """Execute AI tool calls using real services on behalf of a trainer."""

    def __init__(self, db: Session, settings: Settings, trainer_id: str, trainer_user_id: str) -> None:
        self.db = db
        self.settings = settings
        self.trainer_id = trainer_id
        self.trainer_user_id = trainer_user_id
        self.trainer_service = TrainerService(db)
        self.join_service = JoinRequestService(db, settings)

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name in _DESTRUCTIVE_TOOLS_DISABLED:
            log.warning("tool_disabled_refused", tool=name, trainer_id=self.trainer_id)
            result = {"error": f"Tool '{name}' is not available. This action requires explicit confirmation and cannot be performed by the AI automatically."}
            return json.dumps(result)
        try:
            raw = self._dispatch(name, arguments)
            result_str = json.dumps(raw, default=str)
            # Audit: log name, safe args (no secrets), and a short result summary
            safe_args = {k: v for k, v in arguments.items() if k not in ("password", "token", "secret")}
            summary = result_str[:200]
            log.info("ai_tool_call", tool=name, args=safe_args, result_summary=summary, trainer_id=self.trainer_id)
            return result_str
        except Exception as exc:
            log.warning("tool_exec_error", tool=name, error=str(exc), trainer_id=self.trainer_id)
            return json.dumps({"error": str(exc)})

    def _dispatch(self, name: str, args: dict[str, Any]) -> Any:
        if name == "list_trainees":
            return self._list_trainees()
        if name == "list_plans":
            return self._list_plans()
        if name == "create_plan":
            return self._create_plan(args)
        if name == "assign_plan":
            return self._assign_plan(args)
        if name == "unassign_plan":
            return self._unassign_plan(args)
        if name == "send_feedback":
            return self._send_feedback(args)
        if name == "list_join_requests":
            return self._list_join_requests()
        if name == "accept_join_request":
            return self._accept_join_request(args)
        if name == "reject_join_request":
            return self._reject_join_request(args)
        if name == "remove_trainee":
            return self._remove_trainee(args)
        return {"error": f"Unknown tool: {name}"}

    def _list_trainees(self) -> list[dict]:
        items = self.trainer_service.list_trainees(self.trainer_id)
        return [
            {
                "trainee_id": t.id,
                "name": t.user.name if t.user else "Unknown",
                "goal": t.goal,
                "daily_calorie_target": t.daily_calorie_target,
                "current_plan": t.assigned_plan.title if t.assigned_plan else None,
            }
            for t in items
        ]

    def _list_plans(self) -> list[dict]:
        plans = self.trainer_service.list_plans(self.trainer_id)
        return [
            {
                "plan_id": p.id,
                "title": p.title,
                "focus": p.focus,
                "level": p.level,
                "days_per_week": p.days_per_week,
            }
            for p in plans
        ]

    def _create_plan(self, args: dict) -> dict:
        title = args["title"]
        focus = args["focus"]
        notes = args.get("notes")
        days_raw = args.pop("days", None) or []

        if len(title) > _PLAN_MAX_TITLE:
            return {"error": f"limit exceeded: title length {len(title)} exceeds {_PLAN_MAX_TITLE} characters."}
        if len(focus) > _PLAN_MAX_FOCUS:
            return {"error": f"limit exceeded: focus length {len(focus)} exceeds {_PLAN_MAX_FOCUS} characters."}
        if notes and len(notes) > _PLAN_MAX_NOTES:
            return {"error": f"limit exceeded: notes length {len(notes)} exceeds {_PLAN_MAX_NOTES} characters."}
        if len(days_raw) > _PLAN_MAX_DAYS:
            return {"error": f"limit exceeded: {len(days_raw)} days exceeds maximum of {_PLAN_MAX_DAYS}."}

        days = []
        for d in days_raw:
            raw_exercises = d.get("exercises") or []
            if len(raw_exercises) > _PLAN_MAX_EXERCISES_PER_DAY:
                return {"error": f"limit exceeded: {len(raw_exercises)} exercises in day '{d.get('weekday')}' exceeds maximum of {_PLAN_MAX_EXERCISES_PER_DAY}."}
            exercises = []
            for e in raw_exercises:
                prescribed = e.get("prescribed_sets") or []
                if len(prescribed) > _PLAN_MAX_SETS_PER_EXERCISE:
                    return {"error": f"limit exceeded: {len(prescribed)} prescribed sets exceeds maximum of {_PLAN_MAX_SETS_PER_EXERCISE}."}
                exercises.append(PlanDayExerciseIn(
                    exercise_id=e["exercise_id"],
                    sets=e.get("sets", 3),
                    reps=e.get("reps", 10),
                    rest_seconds=e.get("rest_seconds", 60),
                ))
            days.append(PlanDayIn(
                weekday=d["weekday"],
                title=d["title"],
                focus=d["focus"],
                duration_minutes=d.get("duration_minutes", args.get("duration_minutes", 45)),
                exercises=exercises,
            ))
        payload = CreatePlanRequest(
            title=title,
            focus=focus,
            duration_minutes=args["duration_minutes"],
            level=args["level"],
            days_per_week=args["days_per_week"],
            notes=notes,
            days=days,
        )
        plan = self.trainer_service.create_plan(self.trainer_id, payload)
        return {"plan_id": plan.id, "title": plan.title, "status": "created"}

    def _assign_plan(self, args: dict) -> dict:
        payload = AssignPlanRequest(plan_id=args["plan_id"], trainee_id=args["trainee_id"])
        result = self.trainer_service.assign_plan(self.trainer_id, payload)
        return {"status": "assigned", "plan": result.plan.title}

    def _unassign_plan(self, args: dict) -> dict:
        assignment = AssignmentRepository(self.db).get_for_trainee(args["trainee_id"])
        if not assignment:
            return {"error": "No plan is currently assigned to this trainee."}
        self.trainer_service.unassign_plan(self.trainer_id, assignment_id=assignment.id)
        return {"status": "unassigned", "trainee_id": args["trainee_id"]}

    def _send_feedback(self, args: dict) -> dict:
        msg = args["message"]
        if len(msg) > _FEEDBACK_MAX_MSG:
            return {"error": f"limit exceeded: message length {len(msg)} exceeds {_FEEDBACK_MAX_MSG} characters."}
        payload = CreateFeedbackRequest(
            trainee_id=args["trainee_id"],
            message=msg,
            related_exercise_id=args.get("related_exercise_id"),
        )
        fb = self.trainer_service.save_feedback(self.trainer_id, payload)
        return {"status": "sent", "feedback_id": fb.id}

    def _list_join_requests(self) -> list[dict]:
        items = self.join_service.list_for_trainer(
            trainer_user_id=self.trainer_user_id,
            status="pending",
        )
        return [
            {
                "request_id": r.id,
                "trainee_name": r.trainee.name if r.trainee else "Unknown",
                "message": r.message,
                "status": r.status,
                "created_at": str(r.created_at),
            }
            for r in items
        ]

    def _accept_join_request(self, args: dict) -> dict:
        result = self.join_service.accept(
            trainer_id=self.trainer_id,
            trainer_user_id=self.trainer_user_id,
            request_id=args["request_id"],
        )
        return {"status": "accepted", "request_id": result.id}

    def _reject_join_request(self, args: dict) -> dict:
        payload = RejectJoinRequest(reason=args.get("reason")) if args.get("reason") else None
        result = self.join_service.reject(
            trainer_id=self.trainer_id,
            trainer_user_id=self.trainer_user_id,
            request_id=args["request_id"],
            payload=payload,
        )
        return {"status": "rejected", "request_id": result.id}

    def _remove_trainee(self, args: dict) -> dict:
        self.trainer_service.remove_trainee(self.trainer_id, args["trainee_id"])
        return {"status": "removed", "trainee_id": args["trainee_id"]}
