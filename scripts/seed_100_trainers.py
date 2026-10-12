#!/usr/bin/env python3
"""Seed 100 public coaches across 4 Pakistani cities (idempotent).

    .venv/bin/python -m scripts.seed_100_trainers

Credentials written to: docs/SEED_100_TRAINERS.md
Default password for all: CoachDemo100!
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

PASSWORD = "CoachDemo100!"
PREFIX = "bulk"
CITIES = [
    ("Lahore", "Iron Hub", ["strength", "hypertrophy"]),
    ("Karachi", "Coastal Fit", ["fat-loss", "conditioning"]),
    ("Islamabad", "Capital Strength", ["mobility", "rehab"]),
    ("Faisalabad", "Textile Athletics", ["strength", "fat-loss"]),
]

# 100 display names (first + last), deterministic
FIRST = [
    "Ahmad", "Bilal", "Hassan", "Usman", "Zain", "Omar", "Farhan", "Imran",
    "Junaid", "Kamran", "Naveed", "Rizwan", "Saad", "Tariq", "Waqas", "Yasir",
    "Adeel", "Danish", "Fahad", "Hamza", "Irfan", "Kashif", "Luqman", "Majid",
    "Noman", "Ayesha", "Fatima", "Hira", "Iqra", "Maria", "Nadia", "Sana",
    "Zara", "Amna", "Bushra", "Dua", "Emaan", "Gul", "Hina", "Kiran",
    "Laiba", "Mehwish", "Noor", "Rabia", "Saba", "Tania", "Umaima", "Varda",
    "Warda", "Zoya",
]
LAST = [
    "Khan", "Ahmed", "Ali", "Raza", "Malik", "Hussain", "Sheikh", "Butt",
    "Qureshi", "Siddiqui", "Mirza", "Chaudhry", "Baig", "Ansari", "Hashmi",
    "Javed", "Nawaz", "Rehman", "Shah", "Akhtar",
]

SPECIALTY_LABEL = {
    "Lahore": "Strength & hypertrophy",
    "Karachi": "Fat loss & conditioning",
    "Islamabad": "Mobility & rehab",
    "Faisalabad": "Strength & fat loss",
}


def _name(i: int) -> str:
    return f"{FIRST[(i - 1) % len(FIRST)]} {LAST[(i - 1) % len(LAST)]}"


def _city_for(i: int) -> tuple[str, str, list[str]]:
    # 1–25 Lahore, 26–50 Karachi, 51–75 Islamabad, 76–100 Faisalabad
    return CITIES[(i - 1) // 25]


def build_rows() -> list[dict]:
    rows: list[dict] = []
    for i in range(1, 101):
        city, gym, specialties = _city_for(i)
        name = _name(i)
        email = f"coach{i:03d}@tactech.app"
        slug = f"{PREFIX}{i:03d}"
        rows.append(
            {
                "n": i,
                "name": name,
                "email": email,
                "password": PASSWORD,
                "city": city,
                "user_id": f"user-{slug}",
                "trainer_id": f"trainer-{slug}",
                "profile_id": f"cp-{slug}",
                "invite_code": f"TACT-{i:03d}",
                "specialty": SPECIALTY_LABEL[city],
                "specialties": specialties,
                "gym_name": gym,
                "years_experience": 2 + ((i - 1) % 12),
                "headline": f"{SPECIALTY_LABEL[city]} · {city}"[:80],
                "bio": (
                    f"{name} coaches clients in {city}. "
                    f"Focus: {', '.join(specialties)}. "
                    "Online + in-person available."
                ),
                "trainer_bio": f"Coach based in {city}.",
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
            # Email taken by another id — skip to stay idempotent/safe
            continue
        if user is None:
            user = models.User(
                id=item["user_id"],
                name=item["name"],
                email=item["email"],
                password_hash=password_hash,
                role="trainer",
                created_at=now,
                assessment_completed=True,
                onboarding_completed=True,
                location=item["city"],
            )
            db.add(user)
            db.flush()
            created += 1
        else:
            user.name = item["name"]
            user.password_hash = password_hash
            user.role = "trainer"
            user.assessment_completed = True
            user.onboarding_completed = True
            user.location = item["city"]
            updated += 1

        trainer = db.get(models.TrainerProfile, item["trainer_id"])
        if trainer is None:
            trainer = models.TrainerProfile(
                id=item["trainer_id"],
                user_id=item["user_id"],
                invite_code=item["invite_code"],
                specialty=item["specialty"],
                years_experience=item["years_experience"],
                bio=item["trainer_bio"],
            )
            db.add(trainer)
            db.flush()
        else:
            trainer.specialty = item["specialty"]
            trainer.years_experience = item["years_experience"]
            trainer.bio = item["trainer_bio"]

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
            db.flush()

        profile.headline = item["headline"]
        profile.bio = item["bio"]
        profile.city = item["city"]
        profile.country_code = "PK"
        profile.specialties = list(item["specialties"])
        profile.languages = ["en", "ur"]
        profile.gym_name = item["gym_name"]
        profile.years_experience = item["years_experience"]
        profile.is_public = True
        if not getattr(profile, "follow_mode", None):
            profile.follow_mode = "manual"
        if profile.verification_status is None:
            profile.verification_status = "none"
        profile.updated_at = now
        db.flush()
    return created, updated


def write_credentials(rows: list[dict], path: Path) -> None:
    by_city: dict[str, list[dict]] = {}
    for r in rows:
        by_city.setdefault(r["city"], []).append(r)

    lines = [
        "# Seed: 100 trainers (4 cities)",
        "",
        f"**Shared password (all accounts):** `{PASSWORD}`",
        "",
        "| # | Name | Email | City | Password |",
        "|---|------|-------|------|----------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['n']} | {r['name']} | `{r['email']}` | {r['city']} | `{PASSWORD}` |"
        )
    lines.extend(["", "## By city", ""])
    for city, items in by_city.items():
        lines.append(f"### {city} ({len(items)})")
        lines.append("")
        for r in items:
            lines.append(f"- **{r['name']}** — `{r['email']}` / `{PASSWORD}`")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    json_path = path.with_suffix(".json")
    json_path.write_text(
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
    log = get_logger("tactech.seed_100_trainers")
    rows = build_rows()
    password_hash = hash_password(PASSWORD)
    db = SessionLocal()
    try:
        created, updated = upsert(db, rows, password_hash)
        db.commit()
        out = Path(__file__).resolve().parents[1] / "docs" / "SEED_100_TRAINERS.md"
        write_credentials(rows, out)
        log.info(
            "seed_100_trainers_ok",
            created=created,
            updated=updated,
            total=len(rows),
            out=str(out),
        )
        print(f"OK created={created} updated={updated} total={len(rows)}")
        print(f"Credentials: {out}")
        print(f"Password (all): {PASSWORD}")
        for city, _, _ in CITIES:
            n = sum(1 for r in rows if r["city"] == city)
            print(f"  {city}: {n}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
