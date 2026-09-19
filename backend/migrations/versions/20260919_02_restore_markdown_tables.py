"""Recheck source Markdown tables flattened by the legacy editor."""

from alembic import op


revision = "20260919_02"
down_revision = "20260919_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE submission_documents SET source_images_checked_at = NULL WHERE source_file_id IS NOT NULL")


def downgrade() -> None:
    pass
