"""Add agent result import batches."""

import sqlalchemy as sa
from alembic import op


revision = "20261109_02"
down_revision = "20261109_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "agent_import_batches" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "agent_import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.Unicode(255), nullable=False),
        sa.Column("status", sa.Unicode(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_import_batches_teacher_id", "agent_import_batches", ["teacher_id"])
    op.create_index("ix_agent_import_batches_assignment_id", "agent_import_batches", ["assignment_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "agent_import_batches" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("agent_import_batches")
