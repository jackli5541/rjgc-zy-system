"""Add immediate peer and teacher assessments for submitted work."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_10"
down_revision = "20260916_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "submission_assessments" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "submission_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("grade", sa.String(length=1), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('PEER', 'TEACHER')", name="ck_submission_assessment_kind"),
        sa.CheckConstraint("grade IN ('A', 'B', 'C', 'D', 'E')", name="ck_submission_assessment_grade"),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_version_id"], ["submission_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evaluator_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_version_id", "evaluator_id", "kind", name="uq_submission_assessment_evaluator"),
    )
    for column in ("assignment_id", "submission_version_id", "evaluator_id", "subject_user_id"):
        op.create_index(f"ix_submission_assessments_{column}", "submission_assessments", [column])


def downgrade() -> None:
    op.drop_table("submission_assessments")
