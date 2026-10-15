#!/usr/bin/env python3
"""Apply Form Studio 3D metadata pack to the exercises catalog (idempotent).

    .venv/bin/python -m scripts.seed_exercise_form3d
    .venv/bin/python -m scripts.seed_exercise_form3d --pack data/exercises_form3d_seed.json

Does not rename or delete exercise ids. Sets form3dEnabled=false for cardio /
rows without clips. Existing plan/log FKs stay valid.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db import models
from app.db.session import SessionLocal

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK = ROOT / "data" / "exercises_form3d_seed.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def apply_pack(db, pack: dict) -> tuple[int, int]:
    updated = 0
    missing = 0
    default_character = pack.get("character") or "x_bot"
    for item in pack.get("exercises") or []:
        eid = item.get("id")
        if not eid:
            continue
        row = db.get(models.Exercise, eid)
        if row is None:
            missing += 1
            continue
        if item.get("name"):
            row.name = item["name"]
        if item.get("category") is not None:
            row.category = item["category"]
        if item.get("muscles") is not None:
            row.muscles = list(item["muscles"])
        if item.get("level") is not None:
            row.level = str(item["level"]).lower()
        if item.get("equipmentList") is not None:
            row.equipment_list = list(item["equipmentList"])
        if item.get("instructions") is not None:
            row.instructions = item["instructions"]
        if item.get("commonMistakes") is not None:
            row.common_mistakes = list(item["commonMistakes"])
        if item.get("thumbnailUrl") is not None:
            row.thumbnail_url = item["thumbnailUrl"]
        if item.get("mixamoQuery") is not None:
            row.mixamo_query = item["mixamoQuery"]
        if item.get("sortOrder") is not None:
            row.sort_order = int(item["sortOrder"])

        f3 = item.get("form3d") or {}
        enabled = bool(f3.get("enabled"))
        row.form3d_enabled = enabled
        row.form3d_clip_id = f3.get("clipId")
        row.form3d_character = f3.get("character") or (default_character if enabled else None)
        row.form3d_animation_url = f3.get("animationUrl")
        row.form3d_guide = list(f3.get("guide") or [])
        row.form3d_cues = list(f3.get("cues") or [])
        row.active = True if item.get("active", True) else False
        row.updated_at = _utcnow()
        updated += 1
    db.flush()
    return updated, missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed exercise form3d metadata")
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("tactech.seed_exercise_form3d")

    pack = json.loads(args.pack.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        updated, missing = apply_pack(db, pack)
        db.commit()
        log.info(
            "seed_exercise_form3d_ok",
            updated=updated,
            missing=missing,
            pack=str(args.pack),
        )
        print(f"OK updated={updated} missing={missing} pack={args.pack}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
