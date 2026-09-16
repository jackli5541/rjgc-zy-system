"""Add automatic review configuration to assignments."""

import sqlalchemy as sa
from alembic import op

revision = "20260915_05"
down_revision = "20260915_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("assignments")}
    if "auto_review_enabled" not in columns:
        op.add_column("assignments", sa.Column("auto_review_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "auto_review_mode" not in columns:
        op.add_column("assignments", sa.Column("auto_review_mode", sa.String(length=16), nullable=True))
    if "auto_review_criteria_text" not in columns:
        op.add_column("assignments", sa.Column("auto_review_criteria_text", sa.Text(), nullable=True))
    if "auto_review_due_at" not in columns:
        op.add_column("assignments", sa.Column("auto_review_due_at", sa.DateTime(timezone=True), nullable=True))
    if "auto_review_status" not in columns:
        op.add_column("assignments", sa.Column("auto_review_status", sa.String(length=16), nullable=True))
    if "auto_review_error" not in columns:
        op.add_column("assignments", sa.Column("auto_review_error", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("assignments", "auto_review_error")
    op.drop_column("assignments", "auto_review_status")
    op.drop_column("assignments", "auto_review_due_at")
    op.drop_column("assignments", "auto_review_criteria_text")
    op.drop_column("assignments", "auto_review_mode")
    op.drop_column("assignments", "auto_review_enabled")
