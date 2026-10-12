"""Add teacher-facing AI grading jobs and drafts."""

import sqlalchemy as sa
from alembic import op


revision = "20261012_01"
down_revision = "20261007_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "ai_grading_jobs" not in tables:
        op.create_table(
            "ai_grading_jobs",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("assignment_id", sa.Uuid(), nullable=False),
            sa.Column("teacher_id", sa.Uuid(), nullable=False),
            sa.Column("status", sa.Unicode(16), nullable=False),
            sa.Column("total_count", sa.Integer(), nullable=False),
            sa.Column("completed_count", sa.Integer(), nullable=False),
            sa.Column("failed_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ai_grading_jobs_assignment_id", "ai_grading_jobs", ["assignment_id"])
        op.create_index("ix_ai_grading_jobs_teacher_id", "ai_grading_jobs", ["teacher_id"])
        op.create_index("ix_ai_grading_jobs_status", "ai_grading_jobs", ["status"])
    if "ai_grading_drafts" not in tables:
        op.create_table(
            "ai_grading_drafts",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("job_id", sa.Uuid(), nullable=True),
            sa.Column("assignment_id", sa.Uuid(), nullable=False),
            sa.Column("submission_version_id", sa.Uuid(), nullable=False),
            sa.Column("teacher_id", sa.Uuid(), nullable=False),
            sa.Column("assignment_version", sa.Integer(), nullable=False),
            sa.Column("status", sa.Unicode(16), nullable=False),
            sa.Column("model_name", sa.Unicode(100), nullable=True),
            sa.Column("rubric_snapshot", sa.JSON(), nullable=False),
            sa.Column("analysis", sa.JSON(), nullable=True),
            sa.Column("suggested_grade", sa.Unicode(1), nullable=True),
            sa.Column("suggested_comment", sa.UnicodeText(), nullable=True),
            sa.Column("error_message", sa.UnicodeText(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["job_id"], ["ai_grading_jobs.id"]),
            sa.ForeignKeyConstraint(["submission_version_id"], ["submission_versions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("submission_version_id", "teacher_id", "status", name="uq_ai_grading_draft_current"),
        )
        op.create_index("ix_ai_grading_drafts_job_id", "ai_grading_drafts", ["job_id"])
        op.create_index("ix_ai_grading_drafts_assignment_id", "ai_grading_drafts", ["assignment_id"])
        op.create_index("ix_ai_grading_drafts_submission_version_id", "ai_grading_drafts", ["submission_version_id"])
        op.create_index("ix_ai_grading_drafts_teacher_id", "ai_grading_drafts", ["teacher_id"])
        op.create_index("ix_ai_grading_drafts_status", "ai_grading_drafts", ["status"])
        op.create_index("ix_ai_grading_draft_lookup", "ai_grading_drafts", ["assignment_id", "submission_version_id", "created_at"])


def downgrade() -> None:
    op.drop_table("ai_grading_drafts")
    op.drop_table("ai_grading_jobs")
