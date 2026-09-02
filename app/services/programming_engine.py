from __future__ import annotations

from dataclasses import dataclass

from app.schemas.assessment import AssessmentRequest

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_SPREAD = {
    1: (2,),
    2: (1, 3),
    3: (0, 2, 4),
    4: (0, 1, 3, 4),
    5: (0, 1, 2, 3, 4),
    6: (0, 1, 2, 3, 4, 5),
    7: (0, 1, 2, 3, 4, 5, 6),
}


@dataclass(frozen=True)
class Move:
    name: str
    muscle: str
    equipment: str
    difficulty: str
    cues: list[str]
    tags: frozenset[str]
    load: str


LIBRARY: list[Move] = [
    Move("Sit to Stand", "Legs", "Bodyweight", "Beginner", ["sit tall", "drive through mid-foot"], frozenset({"knee_safe", "obese_safe", "beginner"}), "bw"),
    Move("Goblet Box Squat", "Legs", "Dumbbell", "Beginner", ["sit to the box", "knees track toes"], frozenset({"knee_safe", "obese_safe", "beginner", "lift"}), "db"),
    Move("Leg Press Limited ROM", "Legs", "Machine", "Beginner", ["short range", "do not lock out painfully"], frozenset({"knee_safe", "obese_safe", "lift"}), "machine"),
    Move("Hip Thrust", "Glutes", "Barbell", "Intermediate", ["ribs down", "squeeze glutes"], frozenset({"back_safe", "knee_safe", "lift"}), "bar"),
    Move("Glute Bridge", "Glutes", "Bodyweight", "Beginner", ["posterior tilt", "do not arch the low back"], frozenset({"back_safe", "knee_safe", "beginner"}), "bw"),
    Move("Seated Row", "Back", "Machine", "Beginner", ["pull to the ribs", "do not shrug"], frozenset({"back_safe", "knee_safe", "obese_safe", "lift"}), "machine"),
    Move("Lat Pulldown", "Back", "Machine", "Beginner", ["long spine", "pull elbows down"], frozenset({"back_safe", "knee_safe", "obese_safe", "lift"}), "machine"),
    Move("Chest Press Machine", "Chest", "Machine", "Beginner", ["shoulder blades set", "control the return"], frozenset({"back_safe", "knee_safe", "obese_safe", "lift"}), "machine"),
    Move("Push Up", "Chest", "Bodyweight", "Beginner", ["hands under shoulders", "ribs down"], frozenset({"back_safe", "lift"}), "bw"),
    Move("Seated Shoulder Press", "Shoulders", "Dumbbell", "Beginner", ["glutes on the seat", "do not flare ribs"], frozenset({"back_safe", "knee_safe", "obese_safe", "lift"}), "db"),
    Move("Dumbbell Row", "Back", "Dumbbell", "Beginner", ["hinge and hold", "pull to the hip"], frozenset({"lift"}), "db"),
    Move("Dead Bug", "Core", "Bodyweight", "Beginner", ["low back pinned", "exhale as you reach"], frozenset({"back_safe", "knee_safe", "beginner"}), "bw"),
    Move("Bird Dog", "Core", "Bodyweight", "Beginner", ["square hips", "long spine"], frozenset({"back_safe", "knee_safe", "beginner"}), "bw"),
    Move("Pallof Press", "Core", "Cable", "Beginner", ["do not rotate", "breathe out"], frozenset({"back_safe", "knee_safe"}), "cable"),
    Move("Farmer Carry", "Full Body", "Dumbbell", "Beginner", ["ribs stacked", "short steps"], frozenset({"back_safe", "obese_safe", "lift"}), "db"),
    Move("Romanian Deadlift", "Posterior", "Barbell", "Intermediate", ["soft knees", "hinge from the hips"], frozenset({"lift"}), "bar"),
    Move("Hip Hinge Drill", "Posterior", "Bodyweight", "Beginner", ["push hips back", "long spine"], frozenset({"back_safe", "beginner"}), "bw"),
    Move("Goblet Squat", "Legs", "Dumbbell", "Beginner", ["elbows inside knees", "chest up"], frozenset({"lift"}), "db"),
    Move("Walking Lunge", "Legs", "Dumbbell", "Beginner", ["long stride", "front knee stacked"], frozenset({"lift"}), "db"),
    Move("Barbell Squat", "Legs", "Barbell", "Intermediate", ["brace", "sit between the hips"], frozenset({"lift"}), "bar"),
    Move("Plank", "Core", "Bodyweight", "Beginner", ["squeeze glutes", "do not sag"], frozenset({"beginner"}), "bw"),
    Move("Easy Walk", "Conditioning", "None", "Beginner", ["nasal breath", "relaxed shoulders"], frozenset({"knee_safe", "asthma_safe", "obese_safe", "walk"}), "none"),
    Move("Incline Walk", "Conditioning", "Treadmill", "Beginner", ["easy talk pace", "no sprint"], frozenset({"asthma_safe", "obese_safe", "walk"}), "none"),
    Move("Easy Jog", "Conditioning", "None", "Intermediate", ["soft landings", "conversational"], frozenset({"asthma_safe", "jog"}), "none"),
    Move("Zone 2 Bike", "Conditioning", "Bike", "Beginner", ["smooth cadence", "you can talk"], frozenset({"knee_safe", "asthma_safe", "obese_safe", "bike"}), "none"),
    Move("Easy Cycle", "Conditioning", "Bike", "Beginner", ["upright torso", "easy gears"], frozenset({"knee_safe", "asthma_safe", "obese_safe", "bike"}), "none"),
    Move("Hiking Intervals", "Conditioning", "None", "Intermediate", ["uphill easy", "downhill control"], frozenset({"hike"}), "none"),
    Move("Bike Sprint", "Conditioning", "Bike", "Advanced", ["smooth cadence", "recover with control"], frozenset({"bike", "interval"}), "none"),
    Move("Cat Cow", "Mobility", "Bodyweight", "Beginner", ["move with breath", "no forcing end range"], frozenset({"back_safe", "yoga", "beginner"}), "bw"),
    Move("World's Greatest Stretch", "Mobility", "Bodyweight", "Beginner", ["long spine", "breathe into the hip"], frozenset({"yoga", "beginner"}), "bw"),
    Move("Sun Breath Flow", "Mobility", "Bodyweight", "Beginner", ["slow", "never force the shoulders"], frozenset({"yoga", "asthma_safe", "beginner"}), "bw"),
]


def _norm(items: list[str]) -> set[str]:
    return {item.strip().lower() for item in items if item and item.strip().lower() != "none"}


def _goal_focus(goal: str) -> str:
    text = goal.lower()
    if "bulk" in text or "muscle" in text:
        return "Hypertrophy"
    if "endurance" in text:
        return "Endurance"
    if "lose" in text or "fat" in text or "weight" in text:
        return "Fat Loss"
    return "Foundation"


def _level_label(score: int) -> str:
    if score <= 3:
        return "Beginner"
    if score <= 6:
        return "Intermediate"
    return "Advanced"


def _sleep_band(sleep: str) -> str:
    text = sleep.lower()
    if "excellent" in text or "great" in text:
        return "high"
    if "insomniac" in text or "bad" in text:
        return "low"
    return "mid"


def _allowed(move: Move, flags: set[str], level: int) -> bool:
    if "knee" in flags or "arthritis" in flags:
        if move.name in {"Barbell Squat", "Walking Lunge", "Goblet Squat", "Hiking Intervals", "Easy Jog"}:
            return False
    if "back" in flags:
        if move.name in {"Romanian Deadlift", "Barbell Squat", "Walking Lunge"}:
            return False
        if "back_safe" not in move.tags and move.muscle in {"Posterior"} and move.name != "Hip Hinge Drill":
            return False
    if "asthma" in flags and "interval" in move.tags:
        return False
    if "obes" in flags and move.difficulty == "Advanced":
        return False
    if level <= 3 and move.difficulty == "Advanced":
        return False
    return True


def _pick(name: str) -> Move:
    for move in LIBRARY:
        if move.name == name:
            return move
    return LIBRARY[0]


def _first_allowed(names: list[str], flags: set[str], level: int) -> Move:
    for name in names:
        move = _pick(name)
        if _allowed(move, flags, level):
            return move
    for move in LIBRARY:
        if _allowed(move, flags, level):
            return move
    return LIBRARY[0]


def _weight(move: Move, weight_kg: float, level: int, experienced: bool) -> float | None:
    if move.load == "none" or move.load == "bw":
        return None
    factor = 0.08 + (level * 0.015)
    if move.load == "db":
        factor *= 0.35
    if move.load == "machine":
        factor *= 0.7
    if not experienced:
        factor *= 0.7
    if level <= 3:
        factor *= 0.8
    return round(max(4.0, weight_kg * factor), 1)


def _sets_for(level: int, muscle_pain: bool) -> tuple[int, int, int, float, str]:
    if level <= 3:
        sets, reps, rest, rpe, tempo = 3, 8, 90, 6.5, "3-1-1"
    elif level <= 6:
        sets, reps, rest, rpe, tempo = 3, 8, 75, 7.5, "3-1-1"
    else:
        sets, reps, rest, rpe, tempo = 4, 6, 90, 8.0, "2-1-1"
    if muscle_pain:
        sets = max(2, sets - 1)
        rest += 15
        rpe = min(rpe, 6.5)
    return sets, reps, rest, rpe, tempo


def _cardio_move(prefs: set[str], flags: set[str], level: int) -> Move:
    if any("bike" in p or "skating" in p for p in prefs):
        return _first_allowed(["Zone 2 Bike", "Easy Cycle"], flags, level)
    if any("walk" in p for p in prefs) or "obes" in flags or "knee" in flags or "arthritis" in flags:
        return _first_allowed(["Easy Walk", "Incline Walk", "Easy Cycle"], flags, level)
    if any("hik" in p for p in prefs) and "knee" not in flags:
        return _first_allowed(["Hiking Intervals", "Incline Walk"], flags, level)
    if any("jog" in p for p in prefs) and "knee" not in flags:
        return _first_allowed(["Easy Jog", "Incline Walk"], flags, level)
    return _first_allowed(["Easy Walk", "Zone 2 Bike"], flags, level)


def _session_kinds(focus: str, n: int, prefs: set[str], sleep: str, flags: set[str], level: int) -> list[str]:
    yoga = any("yoga" in p for p in prefs)
    hard_cap = 3 if sleep == "low" else 4 if sleep == "mid" else n
    kinds: list[str] = []
    if focus == "Hypertrophy":
        strength = min(n, 5)
        kinds = ["strength"] * strength
    elif focus == "Endurance":
        strength = 1 if n <= 3 else 2
        kinds = ["strength"] * min(strength, n)
        kinds += ["cardio"] * (n - len(kinds))
    elif focus == "Fat Loss":
        strength = max(2, n // 2) if n >= 2 else 1
        kinds = ["strength"] * min(strength, n)
        kinds += ["cardio"] * (n - len(kinds))
    else:
        kinds = ["full_body"] * n
    if yoga and n >= 3:
        kinds[-1] = "yoga"
    if "asthma" in flags:
        kinds = ["cardio" if k == "interval" else k for k in kinds]
    hard = {"strength", "full_body", "interval"}
    while sum(1 for k in kinds if k in hard) > hard_cap:
        idx = next(i for i, k in enumerate(kinds) if k in hard)
        kinds[idx] = "cardio"
    if "strength" not in kinds and "full_body" not in kinds:
        kinds[0] = "full_body"
    return kinds[:n]


def _macros(gender: str, weight_kg: float, calories: int, diet: str) -> tuple[int, int, int]:
    vegan = any(token in diet.lower() for token in ("vegan", "plant"))
    protein_per_kg = 2.0 if vegan else 1.8
    protein = int(round(weight_kg * protein_per_kg))
    protein_kcal = protein * 4
    if "keto" in diet.lower() or "paleo" in diet.lower():
        fat = int(round((calories - protein_kcal) * 0.55 / 9))
        carbs = max(20, int(round((calories - protein_kcal - fat * 9) / 4)))
    elif "carbo" in diet.lower():
        carbs = int(round((calories - protein_kcal) * 0.6 / 4))
        fat = max(35, int(round((calories - protein_kcal - carbs * 4) / 9)))
    elif "fruit" in diet.lower():
        carbs = int(round((calories - protein_kcal) * 0.55 / 4))
        fat = max(30, int(round((calories - protein_kcal - carbs * 4) / 9)))
    else:
        carbs = int(round((calories - protein_kcal) * 0.45 / 4))
        fat = max(35, int(round((calories - protein_kcal - carbs * 4) / 9)))
    return protein, carbs, fat


def _clamp_calories(gender: str, calories: int) -> tuple[int, str | None]:
    floor = 1200 if gender.lower().startswith("f") else 1500
    if calories < floor:
        return floor, f"Calorie goal was below TacTech’s safety floor ({floor} kcal). Programmed at {floor} kcal. Get medical clearance before eating less."
    return calories, None


def _supplement_note(takes: bool, supplements: list[str]) -> str:
    if not takes or not supplements:
        return ""
    bits = []
    for item in supplements:
        name = item.strip()
        low = name.lower()
        if "whey" in low:
            bits.append("whey after training")
        elif "creatine" in low:
            bits.append("creatine 5g daily with a meal")
        elif "caffeine" in low:
            bits.append("caffeine not after 2pm")
        elif name:
            bits.append(f"{name} with a meal")
    return "Supplement timing only: " + "; ".join(bits) + ". This is not medical dosing."


def _exercise_payload(move: Move, weight_kg: float, level: int, experienced: bool, muscle_pain: bool, note: str) -> dict:
    sets, reps, rest, rpe, tempo = _sets_for(level, muscle_pain)
    load = _weight(move, weight_kg, level, experienced)
    cardio = "Conditioning" in move.muscle or "Mobility" in move.muscle
    if cardio:
        sets, reps, rest, rpe, tempo = 1, 20 if "Walk" in move.name or "Jog" in move.name or "Bike" in move.name or "Cycle" in move.name or "Hiking" in move.name else 8, 60, 6.0, "easy"
        if "Mobility" in move.muscle:
            sets, reps, rest = 2, 8, 45
    prescribed = []
    for number in range(1, sets + 1):
        bump = 0 if load is None else round(load * (0 if number == 1 else 0.1), 1)
        prescribed.append(
            {
                "setNumber": number,
                "reps": reps,
                "weightKg": None if load is None else round(load + bump, 1),
                "rpe": max(5.0, rpe - 1) if number == 1 else rpe,
            }
        )
    return {
        "exerciseName": move.name,
        "muscleGroup": move.muscle,
        "equipment": move.equipment,
        "difficulty": move.difficulty,
        "cues": list(move.cues),
        "sets": sets,
        "reps": reps,
        "restSeconds": rest,
        "recommendedWeightKg": load,
        "tempo": tempo,
        "rpe": rpe,
        "notes": note,
        "prescribedSets": prescribed,
    }


def generate_program(payload: AssessmentRequest, name: str) -> dict:
    flags = _norm(payload.limitations)
    flags.update({token for token in payload.concerns.lower().replace(",", " ").split() if token in {"knee", "back", "asthma", "elbow"}})
    if "arthritis" in _norm(payload.limitations):
        flags.add("arthritis")
    if "obesity" in _norm(payload.limitations):
        flags.add("obes")
    prefs = _norm(payload.exercise_preferences)
    focus = _goal_focus(payload.goal)
    level = payload.fitness_level
    sleep = _sleep_band(payload.sleep_quality)
    calories, calorie_note = _clamp_calories(payload.gender, payload.calorie_goal)
    protein, carbs, fat = _macros(payload.gender, payload.weight_kg, calories, payload.diet)
    duration = 35 if sleep == "low" else 45 if level <= 6 else 55
    kinds = _session_kinds(focus, payload.days_per_week, prefs, sleep, flags, level)
    weekdays = [WEEKDAYS[i] for i in DAY_SPREAD[payload.days_per_week]]
    muscle_pain = "muscle" in flags or "muscle pain" in " ".join(_norm(payload.limitations))

    avoid: list[str] = []
    mods: list[str] = []
    if "knee" in flags or "arthritis" in flags:
        avoid += ["deep loaded squats", "walking lunges", "box jumps"]
        mods.append("Use sit-to-stand, box squats, or limited-ROM leg press.")
    if "back" in flags:
        avoid += ["loaded flexion", "good mornings", "sit-up crunch volume"]
        mods.append("Hinge lightly or use hip thrust, dead bug, and bird dog.")
    if "asthma" in flags:
        avoid.append("all-out HIIT")
        mods.append("Keep cardio conversational with a longer warmup.")
    if "obes" in flags:
        mods.append("Joint-friendly and supported options first; walk before impact.")
    if muscle_pain:
        mods.append("Lower volume, extra rest, finish with mobility.")
    if payload.concerns.strip():
        mods.append(f"Honor trainee concern: {payload.concerns.strip()}")

    medical = calorie_note
    pain_words = ("pain", "injur", "surgery", "diagnos", "cardio", "heart", "asthma")
    if any(word in payload.concerns.lower() for word in pain_words) or flags.intersection({"knee", "back", "asthma", "arthritis"}):
        extra = "Program is conservative. Get medical clearance if pain worsens."
        medical = f"{medical} {extra}".strip() if medical else extra

    strength_pool = [
        "Goblet Box Squat" if ("knee" in flags or "arthritis" in flags) else "Goblet Squat",
        "Hip Thrust" if "back" in flags else "Romanian Deadlift",
        "Chest Press Machine",
        "Seated Row",
        "Seated Shoulder Press",
        "Dead Bug" if "back" in flags else "Plank",
        "Farmer Carry",
    ]
    if level <= 3:
        strength_pool = ["Sit to Stand", "Chest Press Machine", "Seated Row", "Glute Bridge", "Dead Bug", "Bird Dog"]

    days = []
    for index, kind in enumerate(kinds):
        weekday = weekdays[index]
        if kind == "cardio":
            move = _cardio_move(prefs, flags, level)
            title, day_focus, location = "Easy Aerobic", "Zone 2 / NEAT", "Outdoors"
            moves = [move, _first_allowed(["Sun Breath Flow", "Cat Cow"], flags, level)]
            coach = "Conversational pace only. Stop if breathing becomes panicked."
        elif kind == "yoga":
            title, day_focus, location = "Recovery Mobility", "Breath + tissue", "Home"
            moves = [
                _first_allowed(["Sun Breath Flow"], flags, level),
                _first_allowed(["Cat Cow"], flags, level),
                _first_allowed(["World's Greatest Stretch", "Bird Dog"], flags, level),
            ]
            coach = "Slow range. No forcing end positions."
        elif kind == "full_body":
            title, day_focus, location = "Full Body Foundations", "Learn positions", "Gym"
            moves = [_first_allowed(strength_pool[i : i + 1] or strength_pool, flags, level) for i in range(0, 5)]
            unique: list[Move] = []
            for name in strength_pool:
                move = _first_allowed([name], flags, level)
                if move.name not in {m.name for m in unique}:
                    unique.append(move)
                if len(unique) == 5:
                    break
            moves = unique
            coach = "Teach positions. Stop above pain. Film one set if form AI is available."
        else:
            lower = index % 2 == 0
            title = "Lower Strength" if lower else "Upper Strength"
            day_focus = "Squat / hinge pattern" if lower else "Push / pull"
            location = "Gym"
            names = strength_pool[:3] if lower else strength_pool[2:6]
            moves = []
            for name in names:
                move = _first_allowed([name], flags, level)
                if move.name not in {m.name for m in moves}:
                    moves.append(move)
            coach = "No failed reps. Leave 2–3 reps in reserve if joints complain."

        note = "Stop above pain." if flags else "Quality over load."
        days.append(
            {
                "weekday": weekday,
                "startTime": "07:00",
                "title": title,
                "focus": day_focus,
                "durationMinutes": duration,
                "location": location,
                "warmup": "5–8 min easy + 2 activation drills",
                "cooldown": "3–5 min walk + stretch" if sleep != "low" else "6 min easy walk + long exhale",
                "coachNotes": coach,
                "exercises": [
                    _exercise_payload(move, payload.weight_kg, level, payload.has_experience, muscle_pain, note)
                    for move in moves
                ],
            }
        )

    diet = payload.diet
    vegan = any(token in diet.lower() for token in ("vegan", "plant"))
    fruit = "fruit" in diet.lower()
    nutrition = (
        f"Hit {calories} kcal with about {protein} g protein, {carbs} g carbs, {fat} g fat. "
        + ("Use plant proteins (tofu, lentils, seitan) at 1.8–2.2 g/kg. " if vegan else "Anchor protein at 1.6–2.2 g/kg. ")
        + ("Fruit-heavy days still need a protein source at each meal. " if fruit else "")
        + "Put most carbs around the hardest session. "
        + _supplement_note(payload.takes_supplements, payload.supplements)
    ).strip()

    first = name.split()[0] if name.strip() else "This trainee"
    coach_summary = (
        f"{first} is a {payload.gender.lower()} trainee, age {payload.age}, at fitness level {level}/10 "
        f"working toward {focus.lower()}. TacTech AI built a {payload.days_per_week}-day week biased toward "
        f"{', '.join(payload.exercise_preferences) or 'mixed training'}. "
        f"Watch {', '.join(sorted(flags)) or 'general form'} and keep loads conservative. "
        f"Sleep is {payload.sleep_quality}; session length is {duration} minutes. "
        f"Do not treat body-scan or voice capture as lab data. "
        f"{'Concern on file: ' + payload.concerns.strip() if payload.concerns.strip() else 'No free-text concerns were added.'}"
    )

    level_label = _level_label(level)
    title = {
        "Fat Loss": "Lean Engine Block",
        "Hypertrophy": "Strength Build Block",
        "Endurance": "Aerobic Base Block",
        "Foundation": "First Principles Block",
    }[focus]

    return {
        "traineeUpdate": {
            "goal": payload.goal,
            "weightKg": payload.weight_kg,
            "dailyCalorieTarget": calories,
            "proteinG": protein,
            "carbsG": carbs,
            "fatG": fat,
        },
        "safety": {
            "avoid": avoid,
            "modifications": mods,
            "medicalNote": medical,
        },
        "coachSummary": coach_summary,
        "nutritionNotes": nutrition,
        "plan": {
            "title": title,
            "focus": focus,
            "durationMinutes": duration,
            "level": level_label,
            "daysPerWeek": payload.days_per_week,
            "notes": "Generated by TacTech AI from the Comprehensive Fitness Assessment. Edit freely as the coach.",
            "days": days,
        },
    }
