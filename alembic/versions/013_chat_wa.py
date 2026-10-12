"""WhatsApp-style chat fidelity fields

Revision ID: 013_chat_wa
Revises: 012_me_flags
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_chat_wa"
down_revision: Union[str, None] = "012_me_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_messages", sa.Column("played_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_messages", sa.Column("reply_to_message_id", sa.String(length=64), nullable=True))
    op.add_column("chat_messages", sa.Column("reply_to_text", sa.String(length=160), nullable=True))
    op.add_column("chat_messages", sa.Column("reply_to_sender_name", sa.String(length=120), nullable=True))
    op.add_column("chat_messages", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "chat_messages",
        sa.Column("deleted_for_everyone_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_messages_reply_to",
        "chat_messages",
        "chat_messages",
        ["reply_to_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_chat_messages_reply_to", "chat_messages", ["reply_to_message_id"])

    op.create_table(
        "chat_message_reactions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "message_id",
            sa.String(length=64),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("emoji", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("message_id", "user_id", name="uq_chat_reaction_user"),
    )
    op.create_index("ix_chat_message_reactions_message_id", "chat_message_reactions", ["message_id"])
    op.create_index("ix_chat_message_reactions_user_id", "chat_message_reactions", ["user_id"])


def downgrade() -> None:
    op.drop_table("chat_message_reactions")
    op.drop_constraint("fk_chat_messages_reply_to", "chat_messages", type_="foreignkey")
    op.drop_index("ix_chat_messages_reply_to", table_name="chat_messages")
    op.drop_column("chat_messages", "deleted_for_everyone_at")
    op.drop_column("chat_messages", "edited_at")
    op.drop_column("chat_messages", "reply_to_sender_name")
    op.drop_column("chat_messages", "reply_to_text")
    op.drop_column("chat_messages", "reply_to_message_id")
    op.drop_column("chat_messages", "played_at")
    op.drop_column("chat_messages", "delivered_at")
