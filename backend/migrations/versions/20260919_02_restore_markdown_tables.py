"""Recheck source Markdown tables flattened by the legacy editor."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_02"
down_revision = "20260919_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE submission_documents SET source_images_checked_at = NULL WHERE source_file_id IS NOT NULL")
    bind = op.get_bind()
    if "grade_cap" not in {column["name"] for column in sa.inspect(bind).get_columns("submission_versions")}:
        op.add_column("submission_versions", sa.Column("grade_cap", sa.String(length=1), nullable=True))


def downgrade() -> None:
    op.drop_column("submission_versions", "grade_cap")
