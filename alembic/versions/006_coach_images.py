"""coach message image attachments

Revision ID: 006_coach_images
Revises: 005_ai_coach
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006_coach_images"
down_revision: Union[str, None] = "005_ai_coach"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("coach_messages", sa.Column("image_url", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("coach_messages", "image_url")
