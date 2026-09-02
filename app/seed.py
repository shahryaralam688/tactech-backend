from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db import models
from app.db.session import SessionLocal

FOOD_CATALOG = [
    ("food-chicken", "Grilled Chicken Bowl", ["chicken", "poultry", "grilled"], 165, 31, 0, 3.6),
    ("food-salmon", "Salmon", ["salmon", "fish"], 208, 20, 0, 13),
    ("food-rice", "Brown Rice", ["rice", "grain"], 123, 2.7, 26, 1),
    ("food-avocado", "Avocado", ["avocado"], 160, 2, 9, 15),
    ("food-yogurt", "Greek Yogurt", ["yogurt", "yoghurt", "dairy"], 97, 9, 3.6, 5),
    ("food-banana", "Banana", ["banana", "fruit"], 89, 1.1, 23, 0.3),
    ("food-oats", "Oatmeal", ["oat", "oatmeal", "porridge"], 68, 2.4, 12, 1.4),
    ("food-egg", "Egg", ["egg"], 155, 13, 1.1, 11),
    ("food-broccoli", "Broccoli", ["broccoli", "vegetable", "veggie"], 34, 2.8, 7, 0.4),
    ("food-shake", "Protein Shake", ["shake", "protein", "whey"], 80, 15, 4, 1.5),
    ("food-pizza", "Pizza", ["pizza"], 266, 11, 33, 10),
    ("food-salad", "Salad", ["salad", "greens", "lettuce"], 45, 2, 6, 2),
    ("food-burger", "Burger", ["burger", "hamburger"], 295, 17, 24, 14),
    ("food-pasta", "Pasta", ["pasta", "spaghetti", "noodle"], 131, 5, 25, 1.1),
    ("food-apple", "Apple", ["apple"], 52, 0.3, 14, 0.2),
]

EXERCISES = [
    ("ex-squat", "Barbell Squat", "Legs", "Barbell", "Intermediate", ["Brace your core", "Knees track over toes", "Sit between the hips", "Stand tall at the top"], "figure.strengthtraining.traditional"),
    ("ex-rdl", "Romanian Deadlift", "Posterior", "Barbell", "Intermediate", ["Soft knees", "Hinge from the hips", "Keep the bar close", "Flat back"], "figure.strengthtraining.functional"),
    ("ex-pushup", "Push Up", "Chest", "Bodyweight", "Beginner", ["Hands under shoulders", "Ribs down", "Full lockout", "Control the descent"], "figure.core.training"),
    ("ex-ohp", "Overhead Press", "Shoulders", "Barbell", "Intermediate", ["Glutes tight", "Press up and slightly back", "Don’t flare ribs"], "figure.boxing"),
    ("ex-row", "Bent Over Row", "Back", "Dumbbell", "Intermediate", ["Hinge and hold", "Pull to the hip", "Squeeze the shoulder blades"], "figure.indoor.rowing"),
    ("ex-lunge", "Walking Lunge", "Legs", "Dumbbell", "Beginner", ["Long stride", "Front knee stacked", "Stay tall"], "figure.walk"),
    ("ex-plank", "Plank", "Core", "Bodyweight", "Beginner", ["Squeeze glutes", "Neutral neck", "Don’t sag the hips"], "figure.yoga"),
    ("ex-hiphinge", "Hip Hinge Drill", "Posterior", "Bodyweight", "Beginner", ["Push hips back", "Soft knees", "Long spine"], "figure.flexibility"),
    ("ex-hiit", "Bike Sprint", "Conditioning", "Bike", "Advanced", ["Smooth cadence", "Upright torso", "Recover with control"], "bicycle"),
]


def seed() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("tactech.seed")
    db = SessionLocal()
    try:
        existing = db.execute(select(models.User).where(models.User.id == "user-trainer-maya")).scalar_one_or_none()
        if existing:
            log.info("seed_skipped", reason="demo trainer already exists")
            return

        now = datetime.now(timezone.utc)
        trainer_password = hash_password(settings.seed_trainer_password)
        trainee_password = hash_password(settings.seed_trainee_password)

        users = [
            models.User(id="user-trainer-maya", name="Maya Cole", email="trainer@tactech.app", password_hash=trainer_password, role="trainer", created_at=now - timedelta(days=120)),
            models.User(id="user-jordan", name="Jordan Hale", email="trainee@tactech.app", password_hash=trainee_password, role="trainee", created_at=now - timedelta(days=40)),
            models.User(id="user-priya", name="Priya Shah", email="priya@tactech.app", password_hash=trainee_password, role="trainee", created_at=now - timedelta(days=28)),
            models.User(id="user-marcus", name="Marcus Webb", email="marcus@tactech.app", password_hash=trainee_password, role="trainee", created_at=now - timedelta(days=18)),
            models.User(id="user-elena", name="Elena Voss", email="elena@tactech.app", password_hash=trainee_password, role="trainee", created_at=now - timedelta(days=10)),
        ]
        db.add_all(users)
        db.flush()

        trainer = models.TrainerProfile(
            id="trainer-maya",
            user_id="user-trainer-maya",
            invite_code="TACT-MAYA",
            specialty="Strength, hypertrophy & movement quality",
            years_experience=8,
            bio="Former collegiate athlete. I coach progressive strength with clean technique and sustainable nutrition.",
        )
        db.add(trainer)
        db.flush()

        db.add_all(
            [
                models.TraineeProfile(id="trainee-jordan", user_id="user-jordan", trainer_id="trainer-maya", goal="Build lean muscle", height_cm=178, weight_kg=76, daily_calorie_target=2400),
                models.TraineeProfile(id="trainee-priya", user_id="user-priya", trainer_id="trainer-maya", goal="Improve endurance", height_cm=164, weight_kg=61, daily_calorie_target=1900),
                models.TraineeProfile(id="trainee-marcus", user_id="user-marcus", trainer_id="trainer-maya", goal="Lose fat, keep strength", height_cm=183, weight_kg=92, daily_calorie_target=2200),
                models.TraineeProfile(id="trainee-elena", user_id="user-elena", trainer_id="trainer-maya", goal="Rehab & mobility", height_cm=170, weight_kg=64, daily_calorie_target=2000),
            ]
        )
        db.flush()

        db.add_all(
            [
                models.Exercise(id=eid, name=name, muscle_group=group, equipment=equip, difficulty=diff, cues=cues, icon=icon)
                for eid, name, group, equip, diff, cues, icon in EXERCISES
            ]
        )
        db.flush()

        def we(wid: str, exercise_id: str, sets: int, reps: int, rest: int, kg: float | None, order: int) -> models.WorkoutExercise:
            return models.WorkoutExercise(
                id=wid,
                exercise_id=exercise_id,
                sets=sets,
                reps=reps,
                rest_seconds=rest,
                recommended_weight_kg=kg,
                sort_order=order,
            )

        db.add_all(
            [
                models.WorkoutPlan(
                    id="plan-push",
                    trainer_id="trainer-maya",
                    title="Push Hypertrophy",
                    focus="Chest · Shoulders · Triceps",
                    duration_minutes=45,
                    level="Intermediate",
                    days_per_week=3,
                    exercises=[
                        we("we-push-1", "ex-pushup", 4, 12, 60, None, 0),
                        we("we-push-2", "ex-ohp", 4, 8, 90, 30, 1),
                        we("we-push-3", "ex-plank", 3, 40, 45, None, 2),
                    ],
                ),
                models.WorkoutPlan(
                    id="plan-lower",
                    trainer_id="trainer-maya",
                    title="Lower Body Strength",
                    focus="Quads · Glutes · Hamstrings",
                    duration_minutes=55,
                    level="Intermediate",
                    days_per_week=3,
                    exercises=[
                        we("we-lower-1", "ex-squat", 5, 5, 150, 70, 0),
                        we("we-lower-2", "ex-rdl", 4, 8, 120, 60, 1),
                        we("we-lower-3", "ex-lunge", 3, 10, 75, 16, 2),
                    ],
                ),
                models.WorkoutPlan(
                    id="plan-engine",
                    trainer_id="trainer-maya",
                    title="Engine Builder",
                    focus="Conditioning · Work capacity",
                    duration_minutes=35,
                    level="Advanced",
                    days_per_week=2,
                    exercises=[
                        we("we-engine-1", "ex-hiit", 8, 30, 45, None, 0),
                        we("we-engine-2", "ex-pushup", 3, 15, 40, None, 1),
                        we("we-engine-3", "ex-plank", 3, 45, 30, None, 2),
                    ],
                ),
                models.WorkoutPlan(
                    id="plan-restore",
                    trainer_id="trainer-maya",
                    title="Restore & Move",
                    focus="Mobility · Control",
                    duration_minutes=30,
                    level="Beginner",
                    days_per_week=4,
                    exercises=[
                        we("we-restore-1", "ex-hiphinge", 3, 10, 40, None, 0),
                        we("we-restore-2", "ex-lunge", 3, 8, 45, None, 1),
                        we("we-restore-3", "ex-plank", 3, 30, 30, None, 2),
                    ],
                ),
            ]
        )
        db.flush()

        db.add_all(
            [
                models.PlanAssignment(id="as-jordan", plan_id="plan-lower", trainee_id="trainee-jordan", assigned_at=now - timedelta(days=12)),
                models.PlanAssignment(id="as-priya", plan_id="plan-engine", trainee_id="trainee-priya", assigned_at=now - timedelta(days=8)),
                models.PlanAssignment(id="as-marcus", plan_id="plan-push", trainee_id="trainee-marcus", assigned_at=now - timedelta(days=6)),
                models.PlanAssignment(id="as-elena", plan_id="plan-restore", trainee_id="trainee-elena", assigned_at=now - timedelta(days=4)),
            ]
        )
        db.flush()

        db.add_all(
            [
                models.WorkoutLog(
                    id="log-1",
                    trainee_id="trainee-jordan",
                    plan_id="plan-lower",
                    completed_at=now - timedelta(days=2),
                    duration_minutes=52,
                    sets=[
                        models.WorkoutSetLog(id="s1", exercise_id="ex-squat", set_number=1, reps=5, weight_kg=70),
                        models.WorkoutSetLog(id="s2", exercise_id="ex-squat", set_number=2, reps=5, weight_kg=72.5),
                    ],
                ),
                models.WorkoutLog(
                    id="log-2",
                    trainee_id="trainee-priya",
                    plan_id="plan-engine",
                    completed_at=now - timedelta(days=1),
                    duration_minutes=34,
                    sets=[
                        models.WorkoutSetLog(id="s3", exercise_id="ex-hiit", set_number=1, reps=30, weight_kg=0),
                    ],
                ),
                models.WorkoutLog(
                    id="log-3",
                    trainee_id="trainee-marcus",
                    plan_id="plan-push",
                    completed_at=now - timedelta(days=3),
                    duration_minutes=41,
                    sets=[
                        models.WorkoutSetLog(id="s4", exercise_id="ex-ohp", set_number=1, reps=8, weight_kg=32),
                    ],
                ),
            ]
        )

        db.add_all(
            [
                models.Meal(id="m1", trainee_id="trainee-jordan", name="Greek Yogurt + Banana", eaten_at=now - timedelta(hours=4), portion_grams=250, calories=310, protein=24, carbs=38, fat=7, source="log", is_estimate=False),
                models.Meal(id="m2", trainee_id="trainee-jordan", name="Grilled Chicken Bowl", eaten_at=now - timedelta(hours=1), portion_grams=320, calories=540, protein=48, carbs=42, fat=16, source="scan", is_estimate=True),
                models.Meal(id="m3", trainee_id="trainee-priya", name="Oatmeal", eaten_at=now - timedelta(hours=5), portion_grams=200, calories=280, protein=11, carbs=46, fat=6, source="log", is_estimate=False),
            ]
        )

        db.add_all(
            [
                models.TrainerFeedback(id="fb1", trainer_id="trainer-maya", trainee_id="trainee-jordan", message="Squat depth looked much better this week. Keep the brace before you descend.", created_at=now - timedelta(days=1), related_exercise_id="ex-squat"),
                models.TrainerFeedback(id="fb2", trainer_id="trainer-maya", trainee_id="trainee-priya", message="Great engine session. Next time recover at 70% instead of stopping completely.", created_at=now - timedelta(hours=2), related_exercise_id="ex-hiit"),
            ]
        )

        db.add_all(
            [
                models.FormReport(id="fr1", trainee_id="trainee-jordan", exercise_id="ex-squat", created_at=now - timedelta(hours=1, minutes=30), score=82, cues=["Go a little deeper", "Knees aligned"], rep_count=8),
                models.FormReport(id="fr2", trainee_id="trainee-marcus", exercise_id="ex-pushup", created_at=now - timedelta(days=1), score=74, cues=["Keep your back straight", "Slow down"], rep_count=12),
            ]
        )

        db.add_all(
            [
                models.FoodKnowledge(id=fid, name=name, keywords=keywords, calories=cal, protein=protein, carbs=carbs, fat=fat)
                for fid, name, keywords, cal, protein, carbs, fat in FOOD_CATALOG
            ]
        )

        db.commit()
        log.info("seed_complete", trainer_email="trainer@tactech.app", invite_code="TACT-MAYA")
    except Exception:
        db.rollback()
        log.exception("seed_failed")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
