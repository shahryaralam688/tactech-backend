"""In-app notifications inbox

Revision ID: 011_notif
Revises: 010_chat_rtc
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011_notif"
down_revision: Union[str, None] = "010_chat_rtc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_notifications",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_app_notifications_user_id", "app_notifications", ["user_id"])
    op.create_index("ix_app_notifications_user_created", "app_notifications", ["user_id", "created_at"])
    op.create_index("ix_app_notifications_type", "app_notifications", ["type"])

    op.add_column("device_push_tokens", sa.Column("device_name", sa.String(length=120), nullable=True))
    op.add_column(
        "device_push_tokens",
        sa.Column("app_version", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device_push_tokens", "app_version")
    op.drop_column("device_push_tokens", "device_name")
    op.drop_index("ix_app_notifications_type", table_name="app_notifications")
    op.drop_index("ix_app_notifications_user_created", table_name="app_notifications")
    op.drop_index("ix_app_notifications_user_id", table_name="app_notifications")
    op.drop_table("app_notifications")
