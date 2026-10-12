#!/usr/bin/env python3
"""Seed 100 trainees across 4 Pakistani cities (idempotent).

    .venv/bin/python -m scripts.seed_100_trainees

Credentials: docs/SEED_100_TRAINEES.txt (.md / .json)
Default password for all: TraineeDemo100!

Links each trainee to the matching bulk trainer in the same city
(coach001↔trainee001 …) when that trainer exists.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db import models
from app.db.session import SessionLocal

PASSWORD = "TraineeDemo100!"
PREFIX = "tnee"
CITIES = ["Lahore", "Karachi", "Islamabad", "Faisalabad"]

FIRST = [
    "Arham", "Bakr", "Cabir", "Daniyal", "Ehsan", "Fawad", "Ghulam", "Habib",
    "Ibrahim", "Jabbar", "Khizer", "Latif", "Muneeb", "Nabeel", "Owais", "Parvez",
    "Qasim", "Raheel", "Shahbaz", "Talha", "Umer", "Vaqas", "Wahab", "Younus",
    "Zubair", "Aima", "Bismah", "Celine", "Dania", "Esha", "Fizza", "Ghazal",
    "Hafsa", "Inaya", "Javeria", "Komal", "Laila", "Maham", "Nimra", "Palwasha",
    "Qurat", "Rida", "Sidra", "Tehreem", "Urooj", "Vaneeza", "Wajiha", "Yumna",
    "Zainab", "Aleena",
]
LAST = [
    "Abbasi", "Bajwa", "Cheema", "Dar", "Elahi", "Farooq", "Gillani", "Haider",
    "Iqbal", "Javaid", "Kazmi", "Lodhi", "Mehmood", "Naqvi", "Orakzai", "Paracha",
    "Qazi", "Randhawa", "Suleman", "Tiwana",
]

GOALS = [
    "Build lean muscle",
    "Improve endurance",
    "Lose fat, keep strength",
    "Rehab & mobility",
    "General fitness",
    "Sports performance",
]


def _name(i: int) -> str:
    return f"{FIRST[(i - 1) % len(FIRST)]} {LAST[(i - 1) % len(LAST)]}"


def _city(i: int) -> str:
    return CITIES[(i - 1) // 25]


def build_rows() -> list[dict]:
    rows: list[dict] = []
    for i in range(1, 101):
        city = _city(i)
        name = _name(i)
        email = f"trainee{i:03d}@tactech.app"
        slug = f"{PREFIX}{i:03d}"
        height = 155 + ((i * 3) % 40)
        weight = 52.0 + ((i * 1.7) % 45.0)
        calories = 1800 + ((i * 17) % 900)
        rows.append(
            {
                "n": i,
                "name": name,
                "email": email,
                "password": PASSWORD,
                "city": city,
                "user_id": f"user-{slug}",
                "trainee_id": f"trainee-{slug}",
                "trainer_id": f"trainer-bulk{i:03d}",  # same-index bulk coach if present
                "goal": GOALS[(i - 1) % len(GOALS)],
                "height_cm": int(height),
                "weight_kg": round(weight, 1),
                "daily_calorie_target": int(calories),
            }
        )
    return rows


def upsert(db, rows: list[dict], password_hash: str) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    created = 0
    updated = 0
    for item in rows:
        user = db.get(models.User, item["user_id"])
        by_email = db.scalars(
            select(models.User).where(models.User.email == item["email"])
        ).first()
        if user is None and by_email is not None:
            continue

        if user is None:
            user = models.User(
                id=item["user_id"],
                name=item["name"],
                email=item["email"],
                password_hash=password_hash,
                role="trainee",
                created_at=now,
                assessment_completed=True,
                onboarding_completed=True,
                location=item["city"],
                height_cm=item["height_cm"],
                weight_kg=item["weight_kg"],
            )
            db.add(user)
            db.flush()
            created += 1
        else:
            user.name = item["name"]
            user.password_hash = password_hash
            user.role = "trainee"
            user.assessment_completed = True
            user.onboarding_completed = True
            user.location = item["city"]
            user.height_cm = item["height_cm"]
            user.weight_kg = item["weight_kg"]
            updated += 1

        trainer_id = item["trainer_id"]
        if db.get(models.TrainerProfile, trainer_id) is None:
            trainer_id = None

        trainee = db.get(models.TraineeProfile, item["trainee_id"])
        if trainee is None:
            trainee = models.TraineeProfile(
                id=item["trainee_id"],
                user_id=item["user_id"],
                trainer_id=trainer_id,
                goal=item["goal"],
                height_cm=item["height_cm"],
                weight_kg=item["weight_kg"],
                daily_calorie_target=item["daily_calorie_target"],
            )
            db.add(trainee)
            db.flush()
        else:
            trainee.trainer_id = trainer_id
            trainee.goal = item["goal"]
            trainee.height_cm = item["height_cm"]
            trainee.weight_kg = item["weight_kg"]
            trainee.daily_calorie_target = item["daily_calorie_target"]
            db.flush()

        # Keep credentials row city accurate for docs even if trainer missing
        item["_linked_trainer"] = trainer_id or ""
    return created, updated


def write_credentials(rows: list[dict], path: Path) -> None:
    lines = [
        "TacTech — 100 trainees (4 cities)",
        f"Shared password (all): {PASSWORD}",
        "",
        "City counts:",
    ]
    for city in CITIES:
        lines.append(f"  {city}: 25")
    lines.extend(
        [
            "",
            f"{'#':<4} {'Name':<22} {'Email':<30} {'City':<12} Password",
            "-" * 92,
        ]
    )
    for r in rows:
        lines.append(
            f"{r['n']:<4} {r['name']:<22} {r['email']:<30} {r['city']:<12} {PASSWORD}"
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    md = path.with_suffix(".md")
    md_lines = [
        "# Seed: 100 trainees (4 cities)",
        "",
        f"**Shared password (all accounts):** `{PASSWORD}`",
        "",
        "| # | Name | Email | City | Password |",
        "|---|------|-------|------|----------|",
    ]
    for r in rows:
        md_lines.append(
            f"| {r['n']} | {r['name']} | `{r['email']}` | {r['city']} | `{PASSWORD}` |"
        )
    md_lines.extend(["", "## By city", ""])
    for city in CITIES:
        items = [r for r in rows if r["city"] == city]
        md_lines.append(f"### {city} ({len(items)})")
        md_lines.append("")
        for r in items:
            md_lines.append(f"- **{r['name']}** — `{r['email']}` / `{PASSWORD}`")
        md_lines.append("")
    md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    path.with_suffix(".json").write_text(
        json.dumps(
            [
                {
                    "n": r["n"],
                    "name": r["name"],
                    "email": r["email"],
                    "password": PASSWORD,
                    "city": r["city"],
                }
                for r in rows
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("tactech.seed_100_trainees")
    rows = build_rows()
    password_hash = hash_password(PASSWORD)
    db = SessionLocal()
    try:
        created, updated = upsert(db, rows, password_hash)
        db.commit()
        out = Path(__file__).resolve().parents[1] / "docs" / "SEED_100_TRAINEES.txt"
        write_credentials(rows, out)
        linked = sum(1 for r in rows if r.get("_linked_trainer"))
        log.info(
            "seed_100_trainees_ok",
            created=created,
            updated=updated,
            total=len(rows),
            linked_trainers=linked,
            out=str(out),
        )
        print(f"OK created={created} updated={updated} total={len(rows)} linked={linked}")
        print(f"Credentials: {out}")
        print(f"Password (all): {PASSWORD}")
        for city in CITIES:
            print(f"  {city}: {sum(1 for r in rows if r['city'] == city)}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
