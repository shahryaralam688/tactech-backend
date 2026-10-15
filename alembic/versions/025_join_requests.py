"""Join requests: invite → pending → accept/reject.

Revision ID: 025_join_requests
Revises: 024_trainer_trainee_links
Create Date: 2026-10-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "025_join_requests"
down_revision: Union[str, None] = "024_trainer_trainee_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "join_requests",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "trainee_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainer_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainee_id",
            sa.String(length=64),
            sa.ForeignKey("trainee_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainer_id",
            sa.String(length=64),
            sa.ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("invite_code", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=280), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reject_reason", sa.String(length=280), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_join_requests_trainer_status", "join_requests", ["trainer_user_id", "status"])
    op.create_index("ix_join_requests_trainee_status", "join_requests", ["trainee_user_id", "status"])
    op.create_index(
        "uq_join_requests_trainee_pending",
        "join_requests",
        ["trainee_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_join_requests_trainee_pending", table_name="join_requests")
    op.drop_index("ix_join_requests_trainee_status", table_name="join_requests")
    op.drop_index("ix_join_requests_trainer_status", table_name="join_requests")
    op.drop_table("join_requests")
