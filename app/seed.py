from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

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


def weekly_strength_plan() -> models.WorkoutPlan:
    return models.WorkoutPlan(
        id="plan-strength-block",
        trainer_id="trainer-maya",
        title="4-day strength block",
        focus="Hypertrophy · posterior chain",
        duration_minutes=55,
        level="Intermediate",
        days_per_week=4,
        notes="Eat before evening sessions.",
        exercises=[
            models.WorkoutExercise(
                id="we-block-flat-1",
                exercise_id="ex-squat",
                sets=4,
                reps=5,
                rest_seconds=150,
                recommended_weight_kg=70,
                sort_order=0,
            )
        ],
        days=[
            models.PlanDay(
                id="day-block-tue",
                weekday="tuesday",
                start_time="07:30",
                title="Lower strength",
                focus="Squat pattern",
                duration_minutes=55,
                location="Gym",
                warmup="5 min bike + empty bar",
                cooldown="Walk 3 min, stretch",
                coach_notes="No failed reps. Stop at RPE 8.",
                sort_order=0,
                exercises=[
                    models.PlanExercise(
                        id="pe-block-squat",
                        exercise_id="ex-squat",
                        sort_order=0,
                        sets=4,
                        reps=5,
                        rest_seconds=150,
                        recommended_weight_kg=70,
                        tempo="3-1-1-0",
                        rpe=7.5,
                        notes="Brace, sit between the hips, full depth.",
                        side="Both",
                        prescribed_sets=[
                            models.PlanPrescribedSet(id="ps-block-1", set_number=1, reps=5, weight_kg=60, rpe=6),
                            models.PlanPrescribedSet(id="ps-block-2", set_number=2, reps=5, weight_kg=70, rpe=7.5),
                        ],
                    )
                ],
            )
        ],
    )


def ensure_weekly_sample(db) -> bool:
    existing = db.get(models.WorkoutPlan, "plan-strength-block")
    if existing:
        return False
    db.add(weekly_strength_plan())
    db.flush()
    return True


# Staging / local QA: public coaches with real trainer users so contact → chat works.
PUBLIC_COACH_SEEDS = [
    {
        "user_id": "user-trainer-maya",
        "trainer_id": "trainer-maya",
        "email": "trainer@tactech.app",
        "name": "Maya Cole",
        "invite_code": "TACT-MAYA",
        "profile_id": "cp-maya",
        "headline": "Strength coach · Online + gym",
        "bio": "Progressive strength with clean technique and sustainable nutrition.",
        "city": "Lahore",
        "country_code": "PK",
        "specialties": ["strength", "hypertrophy"],
        "languages": ["en", "ur"],
        "gym_name": "Iron Hub",
        "years_experience": 8,
        "create_user": False,
    },
    {
        "user_id": "user-trainer-ali",
        "trainer_id": "trainer-ali",
        "email": "ali.coach@tactech.app",
        "name": "Ali Khan",
        "invite_code": "TACT-ALI",
        "profile_id": "cp-ali",
        "headline": "Strength coach · Lahore",
        "bio": "Online + in-gym strength programming for busy professionals.",
        "city": "Lahore",
        "country_code": "PK",
        "specialties": ["strength", "hypertrophy"],
        "languages": ["en", "ur"],
        "gym_name": "Iron Hub",
        "years_experience": 5,
        "create_user": True,
        "specialty": "Strength & hypertrophy",
        "trainer_bio": "Barbell-first programming for intermediate lifters.",
    },
    {
        "user_id": "user-trainer-sara",
        "trainer_id": "trainer-sara",
        "email": "sara.coach@tactech.app",
        "name": "Sara Ahmed",
        "invite_code": "TACT-SARA",
        "profile_id": "cp-sara",
        "headline": "Fat-loss & conditioning · Karachi",
        "bio": "Evidence-based fat loss with sustainable habits and conditioning blocks.",
        "city": "Karachi",
        "country_code": "PK",
        "specialties": ["fat-loss", "conditioning"],
        "languages": ["en", "ur"],
        "gym_name": "Coastal Fit",
        "years_experience": 6,
        "create_user": True,
        "specialty": "Fat loss & conditioning",
        "trainer_bio": "I coach busy clients toward sustainable fat loss.",
    },
    {
        "user_id": "user-trainer-omar",
        "trainer_id": "trainer-omar",
        "email": "omar.coach@tactech.app",
        "name": "Omar Raza",
        "invite_code": "TACT-OMAR",
        "profile_id": "cp-omar",
        "headline": "Mobility & rehab · Islamabad",
        "bio": "Post-injury return-to-training and mobility-focused coaching.",
        "city": "Islamabad",
        "country_code": "PK",
        "specialties": ["mobility", "rehab"],
        "languages": ["en", "ur"],
        "gym_name": None,
        "years_experience": 7,
        "create_user": True,
        "specialty": "Mobility & rehab",
        "trainer_bio": "Rehab-informed training for lasting movement quality.",
    },
]


def ensure_billing_products(db, settings) -> int:
    """Upsert Phase 2 boost + Phase 3 AI SKUs."""
    now = datetime.now(timezone.utc)
    boost_catalog = [
        {
            "id": "boost.featured.7d",
            "name": "Featured Boost — 7 days",
            "description": "Appear at the top of Find Coaches for 7 days.",
            "duration_days": 7,
            "tier": "featured",
            "amount_minor": 999,
            "currency": "usd",
            "providers": ["stripe"],
            "stripe_price_id": (settings.stripe_price_boost_7d or "").strip() or None,
            "sort_order": 10,
        },
        {
            "id": "boost.featured.30d",
            "name": "Featured Boost — 30 days",
            "description": "Appear at the top of Find Coaches for 30 days.",
            "duration_days": 30,
            "tier": "featured",
            "amount_minor": 2499,
            "currency": "usd",
            "providers": ["stripe"],
            "stripe_price_id": (settings.stripe_price_boost_30d or "").strip() or None,
            "sort_order": 20,
        },
        # PKR amountMinor = paisa (×100). 299900 = PKR 2,999.00
        {
            "id": "boost.featured.7d.pkr",
            "name": "Featured Boost — 7 days",
            "description": "Appear at the top of Find Coaches for 7 days.",
            "duration_days": 7,
            "tier": "featured",
            "amount_minor": 299900,
            "currency": "pkr",
            "providers": ["jazzcash", "easypaisa"],
            "stripe_price_id": None,
            "sort_order": 30,
        },
        {
            "id": "boost.featured.30d.pkr",
            "name": "Featured Boost — 30 days",
            "description": "Appear at the top of Find Coaches for 30 days.",
            "duration_days": 30,
            "tier": "featured",
            "amount_minor": 799900,
            "currency": "pkr",
            "providers": ["jazzcash", "easypaisa"],
            "stripe_price_id": None,
            "sort_order": 40,
        },
    ]
    ai_catalog = [
        {
            "id": "ai.pro.monthly",
            "name": "AI Coach Pro — Monthly",
            "description": "Unlimited AI coaching, form tips, and diet guidance.",
            "apple_product_id": "ai.pro.monthly",
            "billing_period": "month",
            "amount_minor": 999,
            "currency": "usd",
            "sort_order": 100,
        },
        {
            "id": "ai.pro.yearly",
            "name": "AI Coach Pro — Yearly",
            "description": "Unlimited AI coaching for a year — best value.",
            "apple_product_id": "ai.pro.yearly",
            "billing_period": "year",
            "amount_minor": 7999,
            "currency": "usd",
            "sort_order": 110,
        },
    ]
    touched = 0
    for item in boost_catalog:
        row = db.get(models.BillingProduct, item["id"])
        if row is None:
            row = models.BillingProduct(
                id=item["id"],
                type="boost",
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            touched += 1
        row.type = "boost"
        row.name = item["name"]
        row.description = item["description"]
        row.duration_days = item["duration_days"]
        row.tier = item["tier"]
        row.amount_minor = item["amount_minor"]
        row.currency = item["currency"]
        row.providers = list(item.get("providers") or [])
        row.billing_period = None
        row.apple_product_id = None
        if item.get("stripe_price_id"):
            row.stripe_price_id = item["stripe_price_id"]
        elif item["currency"] == "usd" and not row.stripe_price_id:
            row.stripe_price_id = f"price_test_{item['id'].replace('.', '_')}"
        if item["currency"] == "pkr":
            row.stripe_price_id = None
        row.active = True
        row.sort_order = item["sort_order"]
        row.updated_at = now
        db.flush()

    for item in ai_catalog:
        row = db.get(models.BillingProduct, item["id"])
        if row is None:
            row = models.BillingProduct(
                id=item["id"],
                type="ai",
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            touched += 1
        row.type = "ai"
        row.name = item["name"]
        row.description = item["description"]
        row.duration_days = None
        row.tier = "pro"
        row.amount_minor = item["amount_minor"]
        row.currency = item["currency"]
        row.apple_product_id = item["apple_product_id"]
        row.billing_period = item["billing_period"]
        row.stripe_price_id = None
        row.active = True
        row.sort_order = item["sort_order"]
        row.updated_at = now
        db.flush()
    return touched


def ensure_public_coaches(db, *, trainer_password_hash: str) -> int:
    """Upsert ≥3 public coach_profiles linked to real trainer users."""
    now = datetime.now(timezone.utc)
    created = 0
    for item in PUBLIC_COACH_SEEDS:
        user = db.get(models.User, item["user_id"])
        if user is None and item.get("create_user"):
            user = models.User(
                id=item["user_id"],
                name=item["name"],
                email=item["email"],
                password_hash=trainer_password_hash,
                role="trainer",
                created_at=now,
                assessment_completed=True,
                onboarding_completed=True,
            )
            db.add(user)
            db.flush()
            created += 1

        trainer = db.get(models.TrainerProfile, item["trainer_id"])
        if trainer is None and item.get("create_user"):
            trainer = models.TrainerProfile(
                id=item["trainer_id"],
                user_id=item["user_id"],
                invite_code=item["invite_code"],
                specialty=item.get("specialty", "Coaching"),
                years_experience=int(item.get("years_experience") or 0),
                bio=item.get("trainer_bio", ""),
            )
            db.add(trainer)
            db.flush()

        if db.get(models.User, item["user_id"]) is None:
            continue
        if db.get(models.TrainerProfile, item["trainer_id"]) is None:
            continue

        profile = db.get(models.CoachProfile, item["profile_id"])
        if profile is None:
            profile = db.scalars(
                select(models.CoachProfile).where(
                    models.CoachProfile.trainer_id == item["trainer_id"]
                )
            ).first()
        if profile is None:
            profile = models.CoachProfile(
                id=item["profile_id"],
                trainer_id=item["trainer_id"],
                user_id=item["user_id"],
                created_at=now,
                updated_at=now,
            )
            db.add(profile)
            created += 1

        profile.headline = item["headline"]
        profile.bio = item["bio"]
        profile.city = item["city"]
        profile.country_code = item["country_code"]
        profile.specialties = list(item["specialties"])
        profile.languages = list(item["languages"])
        profile.gym_name = item.get("gym_name")
        profile.years_experience = item.get("years_experience")
        profile.is_public = True
        profile.cover_image_url = None
        if profile.rating_count is None:
            profile.rating_count = 0
        # Phase 7 — Maya verified by default for badge QA
        if item["profile_id"] == "cp-maya":
            profile.is_verified = True
            profile.verified_at = now - timedelta(days=14)
            profile.verification_status = "approved"
        elif not profile.is_verified:
            if profile.verification_status is None:
                profile.verification_status = "none"
        # Phase 9 — Omar auto-accepts follows for QA
        if item["profile_id"] == "cp-omar":
            profile.follow_mode = "auto_accept"
        elif not getattr(profile, "follow_mode", None):
            profile.follow_mode = "manual"
        profile.updated_at = now
        db.flush()
    return created


PACKAGE_SEEDS = [
    # Maya — featured PKR monthly
    (
        "pkg-maya-standard",
        "cp-maya",
        "trainer-maya",
        "user-trainer-maya",
        "Standard Coaching",
        "Custom workout plan + weekly check-ins.",
        1500000,
        "pkr",
        "month",
        30,
        ["Custom plan", "Weekly check-in", "Chat support"],
        "hybrid",
        True,
        0,
    ),
    (
        "pkg-maya-nutrition",
        "cp-maya",
        "trainer-maya",
        "user-trainer-maya",
        "Nutrition Add-on",
        "Macro targets and weekly food feedback.",
        500000,
        "pkr",
        "month",
        30,
        ["Macro targets", "Weekly feedback"],
        "online",
        False,
        1,
    ),
    # Ali — USD
    (
        "pkg-ali-strength",
        "cp-ali",
        "trainer-ali",
        "user-trainer-ali",
        "Strength Block",
        "Barbell-first 8-week strength cycle.",
        9900,
        "usd",
        "month",
        30,
        ["Programming", "Form video reviews"],
        "online",
        True,
        0,
    ),
    # Sara
    (
        "pkg-sara-fatloss",
        "cp-sara",
        "trainer-sara",
        "user-trainer-sara",
        "Fat-Loss Coaching",
        "Sustainable deficit + conditioning.",
        1200000,
        "pkr",
        "month",
        30,
        ["Custom plan", "Check-ins"],
        "hybrid",
        True,
        0,
    ),
]


def ensure_coach_packages(db) -> int:
    """Upsert staging packages on public coaches."""
    now = datetime.now(timezone.utc)
    touched = 0
    for (
        pid,
        cpid,
        tid,
        uid,
        title,
        desc,
        amount,
        currency,
        period,
        days,
        includes,
        delivery,
        featured,
        sort_order,
    ) in PACKAGE_SEEDS:
        if db.get(models.CoachProfile, cpid) is None:
            continue
        row = db.get(models.CoachPackage, pid)
        if row is None:
            row = models.CoachPackage(
                id=pid,
                coach_profile_id=cpid,
                trainer_id=tid,
                user_id=uid,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            touched += 1
        row.title = title
        row.description = desc
        row.amount_minor = amount
        row.currency = currency
        row.billing_period = period
        row.duration_days = days
        row.includes = list(includes)
        row.delivery = delivery
        row.status = "active"
        row.is_featured = featured
        row.sort_order = sort_order
        row.updated_at = now
        touched += 1
    # Ensure only one featured per coach among seeds
    for cpid in {p[1] for p in PACKAGE_SEEDS}:
        featured_rows = list(
            db.scalars(
                select(models.CoachPackage).where(
                    models.CoachPackage.coach_profile_id == cpid,
                    models.CoachPackage.is_featured.is_(True),
                    models.CoachPackage.status == "active",
                )
            ).all()
        )
        for extra in featured_rows[1:]:
            extra.is_featured = False
    db.flush()
    return touched


def ensure_verification_qa(db) -> int:
    """Seed a rejected application for Ali so trainer rejection UI is testable."""
    now = datetime.now(timezone.utc)
    ali = db.get(models.CoachProfile, "cp-ali")
    if ali is None:
        return 0
    # Don't overwrite if Ali is already verified
    if ali.is_verified:
        return 0
    existing_open = db.scalars(
        select(models.CoachVerificationApplication).where(
            models.CoachVerificationApplication.user_id == ali.user_id,
            models.CoachVerificationApplication.status.in_(("submitted", "under_review", "rejected")),
        )
    ).first()
    if existing_open is not None:
        return 0

    app_id = "verify-ali-rejected"
    if db.get(models.CoachVerificationApplication, app_id) is not None:
        return 0

    app = models.CoachVerificationApplication(
        id=app_id,
        coach_profile_id=ali.id,
        trainer_id=ali.trainer_id,
        user_id=ali.user_id,
        status="rejected",
        legal_full_name="Ali Khan",
        country_code="PK",
        phone_last4=None,
        attestation_accepted=True,
        attestation_accepted_at=now - timedelta(days=3),
        rejection_reason="Certification unreadable. Please re-upload a clearer PDF.",
        reviewer_user_id="admin-seed",
        reviewed_at=now - timedelta(days=2),
        submitted_at=now - timedelta(days=3),
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(days=2),
    )
    db.add(app)
    ali.verification_status = "rejected"
    ali.is_verified = False
    ali.verified_at = None
    db.add(ali)
    db.flush()
    return 1


# Staging QA reviews (Phase 5). Idempotent by deterministic ids.
REVIEW_SEEDS = [
    # Maya — strong ratings
    ("rev-maya-jordan", "cp-maya", "trainer-maya", "user-jordan", "trainee-jordan", 5, "Maya's programming is clear and progressive."),
    ("rev-maya-priya", "cp-maya", "trainer-maya", "user-priya", "trainee-priya", 5, "Very responsive and form cues are excellent."),
    ("rev-maya-marcus", "cp-maya", "trainer-maya", "user-marcus", "trainee-marcus", 4, "Solid strength block. Would like more video demos."),
    # Ali
    ("rev-ali-jordan", "cp-ali", "trainer-ali", "user-jordan", "trainee-jordan", 4, "Great hypertrophy focus for busy schedules."),
    ("rev-ali-elena", "cp-ali", "trainer-ali", "user-elena", "trainee-elena", 5, "Loved the online check-ins."),
    ("rev-ali-priya", "cp-ali", "trainer-ali", "user-priya", "trainee-priya", 3, "Good coach, chat was a bit slow some weeks."),
    # Sara
    ("rev-sara-marcus", "cp-sara", "trainer-sara", "user-marcus", "trainee-marcus", 5, "Fat-loss plan actually stuck. Highly recommend."),
    ("rev-sara-elena", "cp-sara", "trainer-sara", "user-elena", "trainee-elena", 4, "Conditioning sessions are tough but fair."),
    ("rev-sara-jordan", "cp-sara", "trainer-sara", "user-jordan", "trainee-jordan", 4, None),
    # Omar
    ("rev-omar-elena", "cp-omar", "trainer-omar", "user-elena", "trainee-elena", 5, "Best mobility coach I've worked with."),
    ("rev-omar-priya", "cp-omar", "trainer-omar", "user-priya", "trainee-priya", 4, "Rehab-aware and patient."),
    ("rev-omar-marcus", "cp-omar", "trainer-omar", "user-marcus", "trainee-marcus", 2, "Not the right fit for my strength goals."),
]


def ensure_coach_reviews(db) -> int:
    """Upsert staging reviews and recompute coach_profiles aggregates."""
    from decimal import Decimal

    from sqlalchemy import func

    now = datetime.now(timezone.utc)
    touched = 0
    for rid, cpid, tid, uid, trainee_id, stars, body in REVIEW_SEEDS:
        if db.get(models.CoachProfile, cpid) is None:
            continue
        if db.get(models.User, uid) is None:
            continue
        row = db.get(models.CoachReview, rid)
        if row is None:
            # Skip if another review already exists for this author↔coach
            existing = db.scalars(
                select(models.CoachReview).where(
                    models.CoachReview.author_user_id == uid,
                    models.CoachReview.coach_profile_id == cpid,
                )
            ).first()
            if existing is not None:
                continue
            row = models.CoachReview(
                id=rid,
                coach_profile_id=cpid,
                trainer_id=tid,
                author_user_id=uid,
                author_trainee_id=trainee_id if db.get(models.TraineeProfile, trainee_id) else None,
                stars=stars,
                body=body,
                is_hidden=False,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            touched += 1
        else:
            row.stars = stars
            row.body = body
            row.is_hidden = False
            row.updated_at = now
            touched += 1

    db.flush()
    # Recompute aggregates for all seeded coach profiles
    for cpid in {item[1] for item in REVIEW_SEEDS}:
        profile = db.get(models.CoachProfile, cpid)
        if profile is None:
            continue
        avg, count = db.execute(
            select(func.avg(models.CoachReview.stars), func.count(models.CoachReview.id)).where(
                models.CoachReview.coach_profile_id == cpid,
                models.CoachReview.is_hidden.is_(False),
            )
        ).one()
        if count and int(count) > 0:
            profile.rating_count = int(count)
            profile.rating_avg = Decimal(str(round(float(avg), 2)))
        else:
            profile.rating_count = 0
            profile.rating_avg = None
        db.add(profile)
    db.flush()
    return touched


def ensure_analytics_events(db) -> int:
    """Staging sample views/contacts/impressions over last 30 days for iOS charts."""
    import random
    from uuid import uuid4

    from app.repositories.analytics import (
        EVENT_CONTACT,
        EVENT_CONTACT_CREATED,
        EVENT_IMPRESSION,
        EVENT_VIEW,
    )

    now = datetime.now(timezone.utc)
    viewers = [
        ("user-jordan",),
        ("user-priya",),
        ("user-marcus",),
        ("user-elena",),
    ]
    # Only seed if maya has few recent events
    existing = db.scalar(
        select(func.count())
        .select_from(models.CoachProfileEvent)
        .where(
            models.CoachProfileEvent.coach_profile_id == "cp-maya",
            models.CoachProfileEvent.created_at >= now - timedelta(days=30),
        )
    )
    if existing and int(existing) >= 40:
        return 0

    touched = 0
    targets = [
        ("cp-maya", "trainer-maya"),
        ("cp-ali", "trainer-ali"),
        ("cp-sara", "trainer-sara"),
    ]
    rng = random.Random(42)
    for day_offset in range(30):
        day = now - timedelta(days=day_offset)
        for cpid, tid in targets:
            if db.get(models.CoachProfile, cpid) is None:
                continue
            for _ in range(rng.randint(1, 3)):
                viewer = rng.choice(viewers)[0]
                if db.get(models.User, viewer) is None:
                    continue
                db.add(
                    models.CoachProfileEvent(
                        id=str(uuid4()),
                        coach_profile_id=cpid,
                        trainer_id=tid,
                        viewer_user_id=viewer,
                        event_type=EVENT_VIEW,
                        created_at=day.replace(
                            hour=rng.randint(8, 20),
                            minute=rng.randint(0, 59),
                            second=0,
                            microsecond=0,
                        ),
                        meta={"source": "detail", "boostActive": False, "seed": True},
                    )
                )
                touched += 1
            if day_offset % 3 == 0:
                viewer = rng.choice(viewers)[0]
                if db.get(models.User, viewer) is None:
                    continue
                created_at = day.replace(hour=12, minute=0, second=0, microsecond=0)
                db.add(
                    models.CoachProfileEvent(
                        id=str(uuid4()),
                        coach_profile_id=cpid,
                        trainer_id=tid,
                        viewer_user_id=viewer,
                        event_type=EVENT_CONTACT,
                        created_at=created_at,
                        meta={"source": "contact", "created": True, "seed": True},
                    )
                )
                db.add(
                    models.CoachProfileEvent(
                        id=str(uuid4()),
                        coach_profile_id=cpid,
                        trainer_id=tid,
                        viewer_user_id=viewer,
                        event_type=EVENT_CONTACT_CREATED,
                        created_at=created_at,
                        meta={"source": "contact", "seed": True},
                    )
                )
                touched += 2
            if day_offset % 2 == 0:
                viewer = rng.choice(viewers)[0]
                db.add(
                    models.CoachProfileEvent(
                        id=str(uuid4()),
                        coach_profile_id=cpid,
                        trainer_id=tid,
                        viewer_user_id=viewer,
                        event_type=EVENT_IMPRESSION,
                        created_at=day.replace(hour=10, minute=0, second=0, microsecond=0),
                        meta={"source": "discover_list", "seed": True},
                    )
                )
                touched += 1
    db.flush()
    return touched


def seed() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("tactech.seed")
    db = SessionLocal()
    try:
        existing = db.execute(select(models.User).where(models.User.id == "user-trainer-maya")).scalar_one_or_none()
        if existing:
            if ensure_weekly_sample(db):
                log.info("seed_weekly_plan_added", plan_id="plan-strength-block")
            else:
                log.info("seed_skipped", reason="demo trainer already exists")
            n = ensure_public_coaches(db, trainer_password_hash=existing.password_hash)
            bp = ensure_billing_products(db, settings)
            rv = ensure_coach_reviews(db)
            ae = ensure_analytics_events(db)
            vq = ensure_verification_qa(db)
            pk = ensure_coach_packages(db)
            db.commit()
            log.info("seed_public_coaches", created_or_updated=n)
            log.info("seed_billing_products", created_or_updated=bp)
            log.info("seed_coach_reviews", created_or_updated=rv)
            log.info("seed_analytics_events", created_or_updated=ae)
            log.info("seed_verification_qa", created_or_updated=vq)
            log.info("seed_coach_packages", created_or_updated=pk)
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
                weekly_strength_plan(),
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

        n = ensure_public_coaches(db, trainer_password_hash=trainer_password)
        bp = ensure_billing_products(db, settings)
        rv = ensure_coach_reviews(db)
        ae = ensure_analytics_events(db)
        vq = ensure_verification_qa(db)
        pk = ensure_coach_packages(db)
        db.commit()
        log.info(
            "seed_complete",
            trainer_email="trainer@tactech.app",
            invite_code="TACT-MAYA",
            public_coaches=n,
            billing_products=bp,
            coach_reviews=rv,
            analytics_events=ae,
            verification_qa=vq,
            coach_packages=pk,
        )
    except Exception:
        db.rollback()
        log.exception("seed_failed")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
