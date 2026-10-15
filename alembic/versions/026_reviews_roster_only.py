"""Purge coach reviews from authors who were never this coach's trainee; recompute ratings.

Revision ID: 026_reviews_roster_only
Revises: 025_join_requests
Create Date: 2026-10-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "026_reviews_roster_only"
down_revision: Union[str, None] = "025_join_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Delete reviews where author never had an active/ended roster link to that coach's trainer
    # and is not currently linked via trainee_profiles.trainer_id.
    result = conn.execute(
        text(
            """
            DELETE FROM coach_reviews AS cr
            USING coach_profiles AS cp
            WHERE cr.coach_profile_id = cp.id
              AND NOT EXISTS (
                    SELECT 1
                    FROM trainee_profiles AS tp
                    WHERE tp.user_id = cr.author_user_id
                      AND tp.trainer_id = cp.trainer_id
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM trainer_trainee_links AS ttl
                    WHERE ttl.trainee_user_id = cr.author_user_id
                      AND ttl.trainer_id = cp.trainer_id
              )
            """
        )
    )
    purged = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0

    # Recompute aggregates for every coach profile
    conn.execute(
        text(
            """
            UPDATE coach_profiles AS cp
            SET
                rating_count = COALESCE(agg.cnt, 0),
                rating_avg = agg.avg_stars
            FROM (
                SELECT
                    coach_profile_id,
                    COUNT(*)::int AS cnt,
                    ROUND(AVG(stars)::numeric, 2) AS avg_stars
                FROM coach_reviews
                WHERE is_hidden = false
                GROUP BY coach_profile_id
            ) AS agg
            WHERE cp.id = agg.coach_profile_id
            """
        )
    )
    # Coaches with zero remaining reviews
    conn.execute(
        text(
            """
            UPDATE coach_profiles AS cp
            SET rating_count = 0, rating_avg = NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM coach_reviews AS cr
                WHERE cr.coach_profile_id = cp.id AND cr.is_hidden = false
            )
            """
        )
    )

    # Alembic log via print (visible in upgrade output)
    print(f"026_reviews_roster_only: purged {purged} orphan coach_reviews; recomputed rating aggregates")


def downgrade() -> None:
    # Irreversible data cleanup
    pass
