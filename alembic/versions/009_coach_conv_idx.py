"""Index coach conversations (user_id, updated_at)

Revision ID: 009_coach_conv_idx
Revises: 008_human_chat
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "009_coach_conv_idx"
down_revision: Union[str, None] = "008_human_chat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_coach_conversations_user_updated",
        "coach_conversations",
        ["user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_coach_conversations_user_updated", table_name="coach_conversations")
