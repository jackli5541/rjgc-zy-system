"""Store and load workspace Markdown without duplicate rendered HTML."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_01"
down_revision = "20260918_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("submission_documents", sa.Column("source_images_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_column("submission_documents", "content_html")


def downgrade() -> None:
    op.add_column("submission_documents", sa.Column("content_html", sa.UnicodeText(), nullable=False, server_default=""))
    op.drop_column("submission_documents", "source_images_checked_at")
