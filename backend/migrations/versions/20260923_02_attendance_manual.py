"""Add attendance_scores_manual: stopgap manual attendance entry for the grade overview."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_02"
down_revision = "20260923_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = sa.inspect(op.get_bind()).get_table_names()
    if "attendance_scores_manual" not in existing:
        op.create_table(
            "attendance_scores_manual",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("class_id", sa.Uuid(), nullable=False),
            sa.Column("student_user_id", sa.Uuid(), nullable=False),
            sa.Column("score", sa.Numeric(4, 1), nullable=False),
            sa.Column("graded_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["class_id"], ["teaching_classes.id"]),
            sa.ForeignKeyConstraint(["student_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["graded_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("class_id", "student_user_id", name="uq_attendance_manual"),
        )
        op.create_index("ix_attendance_scores_manual_class_id", "attendance_scores_manual", ["class_id"])
        op.create_index("ix_attendance_scores_manual_student_user_id", "attendance_scores_manual", ["student_user_id"])


def downgrade() -> None:
    existing = sa.inspect(op.get_bind()).get_table_names()
    if "attendance_scores_manual" in existing:
        op.drop_table("attendance_scores_manual")
