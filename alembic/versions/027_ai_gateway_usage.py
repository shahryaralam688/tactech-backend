"""AI gateway freemium usage tables (daily chat + lifetime plan gens).

Revision ID: 027
Revises: 026
Create Date: 2026-10-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "027_ai_gateway_usage"
down_revision: Union[str, None] = "026_reviews_roster_only"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_daily",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("usage_day", sa.Date(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "usage_day", name="uq_ai_usage_daily_user_day"),
    )
    op.create_index("ix_ai_usage_daily_user_id", "ai_usage_daily", ["user_id"])

    op.create_table(
        "ai_plan_generation_usage",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("generation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("ai_plan_generation_usage")
    op.drop_index("ix_ai_usage_daily_user_id", table_name="ai_usage_daily")
    op.drop_table("ai_usage_daily")
