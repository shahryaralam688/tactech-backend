"""Phase 3: Apple IAP AI entitlements + product fields + free tease usage

Revision ID: 016_ai_iap
Revises: 015_billing_boost
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "016_ai_iap"
down_revision: Union[str, None] = "015_billing_boost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("billing_products", sa.Column("apple_product_id", sa.String(length=128), nullable=True))
    op.add_column("billing_products", sa.Column("billing_period", sa.String(length=32), nullable=True))
    op.alter_column("billing_products", "duration_days", existing_type=sa.Integer(), nullable=True)
    op.create_index("ix_billing_products_apple_product_id", "billing_products", ["apple_product_id"])

    op.add_column("ai_entitlements", sa.Column("product_id", sa.String(length=64), nullable=True))
    op.add_column("ai_entitlements", sa.Column("apple_product_id", sa.String(length=128), nullable=True))
    op.add_column(
        "ai_entitlements",
        sa.Column("original_transaction_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "ai_entitlements",
        sa.Column("latest_transaction_id", sa.String(length=128), nullable=True),
    )
    op.add_column("ai_entitlements", sa.Column("environment", sa.String(length=32), nullable=True))
    op.add_column(
        "ai_entitlements",
        sa.Column("raw_last_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "ai_entitlements",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_ai_entitlements_product_id",
        "ai_entitlements",
        "billing_products",
        ["product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_ai_entitlements_user_status_ends", "ai_entitlements", ["user_id", "status", "ends_at"])
    op.create_index("ix_ai_entitlements_ends_at", "ai_entitlements", ["ends_at"])
    op.create_index(
        "uq_ai_entitlements_original_transaction_id",
        "ai_entitlements",
        ["original_transaction_id"],
        unique=True,
    )
    # One entitlement row per user (upsert target)
    op.create_index("uq_ai_entitlements_user_id", "ai_entitlements", ["user_id"], unique=True)

    op.create_table(
        "ai_usage_weekly",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "week_start", name="uq_ai_usage_weekly_user_week"),
    )
    op.create_index("ix_ai_usage_weekly_user_id", "ai_usage_weekly", ["user_id"])


def downgrade() -> None:
    op.drop_table("ai_usage_weekly")

    op.drop_index("uq_ai_entitlements_user_id", table_name="ai_entitlements")
    op.drop_index("uq_ai_entitlements_original_transaction_id", table_name="ai_entitlements")
    op.drop_index("ix_ai_entitlements_ends_at", table_name="ai_entitlements")
    op.drop_index("ix_ai_entitlements_user_status_ends", table_name="ai_entitlements")
    op.drop_constraint("fk_ai_entitlements_product_id", "ai_entitlements", type_="foreignkey")
    op.drop_column("ai_entitlements", "updated_at")
    op.drop_column("ai_entitlements", "raw_last_payload")
    op.drop_column("ai_entitlements", "environment")
    op.drop_column("ai_entitlements", "latest_transaction_id")
    op.drop_column("ai_entitlements", "original_transaction_id")
    op.drop_column("ai_entitlements", "apple_product_id")
    op.drop_column("ai_entitlements", "product_id")

    op.drop_index("ix_billing_products_apple_product_id", table_name="billing_products")
    op.alter_column("billing_products", "duration_days", existing_type=sa.Integer(), nullable=False)
    op.drop_column("billing_products", "billing_period")
    op.drop_column("billing_products", "apple_product_id")
