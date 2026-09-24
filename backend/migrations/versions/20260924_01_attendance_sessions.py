"""Replace manual attendance scores with sessions and roster records."""

import sqlalchemy as sa
from alembic import op

revision = "20260924_01"
down_revision = "20260923_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attendance_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("class_id", sa.Uuid(), sa.ForeignKey("teaching_classes.id"), nullable=False),
        sa.Column("title", sa.Unicode(100), nullable=False),
        sa.Column("status", sa.Unicode(16), nullable=False),
        sa.Column("code_secret", sa.LargeBinary(32), nullable=False),
        sa.Column("late_after_minutes", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
    )
    op.create_index("ix_attendance_sessions_class_id", "attendance_sessions", ["class_id"])
    op.create_index("uq_active_attendance_session", "attendance_sessions", ["class_id"], unique=True, mssql_where=sa.text("status = 'ACTIVE'"))
    op.create_table(
        "attendance_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("attendance_sessions.id"), nullable=False),
        sa.Column("student_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("student_no", sa.Unicode(64), nullable=False),
        sa.Column("student_name", sa.Unicode(80), nullable=False),
        sa.Column("status", sa.Unicode(16), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.Unicode(16)),
        sa.Column("note", sa.UnicodeText()),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("failed_window_at", sa.DateTime(timezone=True)),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_id", "student_user_id", name="uq_attendance_record_student"),
    )
    op.create_index("ix_attendance_records_session_id", "attendance_records", ["session_id"])
    op.create_index("ix_attendance_records_student_user_id", "attendance_records", ["student_user_id"])
    op.drop_table("attendance_scores_manual")


def downgrade() -> None:
    op.create_table(
        "attendance_scores_manual",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("class_id", sa.Uuid(), sa.ForeignKey("teaching_classes.id"), nullable=False),
        sa.Column("student_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("score", sa.Numeric(4, 1), nullable=False),
        sa.Column("graded_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("class_id", "student_user_id", name="uq_attendance_manual"),
    )
    op.create_index("ix_attendance_scores_manual_class_id", "attendance_scores_manual", ["class_id"])
    op.create_index("ix_attendance_scores_manual_student_user_id", "attendance_scores_manual", ["student_user_id"])
    op.drop_table("attendance_records")
    op.drop_table("attendance_sessions")
