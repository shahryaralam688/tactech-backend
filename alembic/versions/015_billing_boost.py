"""Phase 2: billing products + coach boost Stripe fields

Revision ID: 015_billing_boost
Revises: 014_coach_discovery
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_billing_boost"
down_revision: Union[str, None] = "014_coach_discovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_products",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("type", sa.String(length=32), nullable=False, index=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(length=64), nullable=False, server_default="featured"),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="usd"),
        sa.Column("stripe_price_id", sa.String(length=128), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("coach_boosts", sa.Column("product_id", sa.String(length=64), nullable=True))
    op.add_column(
        "coach_boosts",
        sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "coach_boosts",
        sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True),
    )
    op.add_column("coach_boosts", sa.Column("amount_minor", sa.Integer(), nullable=True))
    op.add_column(
        "coach_boosts",
        sa.Column("currency", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "coach_boosts",
        sa.Column("source", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "coach_boosts",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_coach_boosts_product_id",
        "coach_boosts",
        "billing_products",
        ["product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_coach_boosts_user_status_ends", "coach_boosts", ["user_id", "status", "ends_at"])
    op.create_index("ix_coach_boosts_ends_at", "coach_boosts", ["ends_at"])
    # Postgres UNIQUE allows multiple NULLs — acts as "unique where not null"
    op.create_index(
        "uq_coach_boosts_stripe_checkout_session",
        "coach_boosts",
        ["stripe_checkout_session_id"],
        unique=True,
    )
    op.create_index(
        "uq_coach_boosts_stripe_payment_intent",
        "coach_boosts",
        ["stripe_payment_intent_id"],
        unique=True,
    )

    op.add_column(
        "payment_events",
        sa.Column("type", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_payment_events_provider_type", "payment_events", ["provider", "type"])


def downgrade() -> None:
    op.drop_index("ix_payment_events_provider_type", table_name="payment_events")
    op.drop_column("payment_events", "type")

    op.drop_index("uq_coach_boosts_stripe_payment_intent", table_name="coach_boosts")
    op.drop_index("uq_coach_boosts_stripe_checkout_session", table_name="coach_boosts")
    op.drop_index("ix_coach_boosts_ends_at", table_name="coach_boosts")
    op.drop_index("ix_coach_boosts_user_status_ends", table_name="coach_boosts")
    op.drop_constraint("fk_coach_boosts_product_id", "coach_boosts", type_="foreignkey")
    op.drop_column("coach_boosts", "updated_at")
    op.drop_column("coach_boosts", "source")
    op.drop_column("coach_boosts", "currency")
    op.drop_column("coach_boosts", "amount_minor")
    op.drop_column("coach_boosts", "stripe_payment_intent_id")
    op.drop_column("coach_boosts", "stripe_checkout_session_id")
    op.drop_column("coach_boosts", "product_id")

    op.drop_table("billing_products")
