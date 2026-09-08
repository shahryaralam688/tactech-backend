"""pgvector for coach memory embeddings

Revision ID: 007_pgvector_memory
Revises: 006_coach_images
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "007_pgvector_memory"
down_revision: Union[str, None] = "006_coach_images"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("DELETE FROM coach_memory_chunks")
    op.execute("ALTER TABLE coach_memory_chunks DROP COLUMN IF EXISTS embedding")
    op.execute(f"ALTER TABLE coach_memory_chunks ADD COLUMN embedding vector({EMBED_DIM})")
    # Cosine search index (autocommit — avoids long lock issues in some Postgres setups)
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_coach_memory_chunks_embedding_hnsw
            ON coach_memory_chunks
            USING hnsw (embedding vector_cosine_ops)
            """
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_coach_memory_chunks_user_updated
        ON coach_memory_chunks (user_id, updated_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_coach_memory_chunks_user_updated")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX IF EXISTS ix_coach_memory_chunks_embedding_hnsw")
    op.execute("ALTER TABLE coach_memory_chunks DROP COLUMN IF EXISTS embedding")
    op.execute(
        "ALTER TABLE coach_memory_chunks ADD COLUMN embedding jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
