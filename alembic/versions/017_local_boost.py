"""Phase 4: JazzCash/Easypaisa boost — providers, attempts, PKR fields

Revision ID: 017_local_boost
Revises: 016_ai_iap
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "017_local_boost"
down_revision: Union[str, None] = "016_ai_iap"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "billing_products",
        sa.Column(
            "providers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.add_column("coach_boosts", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column(
        "coach_boosts",
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "coach_boosts",
        sa.Column("merchant_txn_id", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_coach_boosts_provider", "coach_boosts", ["provider"])
    op.create_index(
        "uq_coach_boosts_provider_payment",
        "coach_boosts",
        ["provider", "provider_payment_id"],
        unique=True,
        postgresql_where=sa.text("provider_payment_id IS NOT NULL"),
    )
    op.create_index(
        "uq_coach_boosts_merchant_txn",
        "coach_boosts",
        ["merchant_txn_id"],
        unique=True,
        postgresql_where=sa.text("merchant_txn_id IS NOT NULL"),
    )

    op.create_table(
        "boost_checkout_attempts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "trainer_id",
            sa.String(length=64),
            sa.ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.String(length=64),
            sa.ForeignKey("billing_products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("merchant_txn_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("redirect_url", sa.String(length=1024), nullable=True),
        sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=True),
        sa.Column(
            "provider_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_boost_attempts_user_status", "boost_checkout_attempts", ["user_id", "status"])


def downgrade() -> None:
    op.drop_table("boost_checkout_attempts")
    op.drop_index("uq_coach_boosts_merchant_txn", table_name="coach_boosts")
    op.drop_index("uq_coach_boosts_provider_payment", table_name="coach_boosts")
    op.drop_index("ix_coach_boosts_provider", table_name="coach_boosts")
    op.drop_column("coach_boosts", "merchant_txn_id")
    op.drop_column("coach_boosts", "provider_payment_id")
    op.drop_column("coach_boosts", "provider")
    op.drop_column("billing_products", "providers")
