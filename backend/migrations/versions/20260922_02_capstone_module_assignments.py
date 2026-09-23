"""Create capstone_module_assignments table for teacher-assigned module names.

Revision ID: 20260922_02
Revises: 20260922_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_02"
down_revision = "20260922_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "capstone_module_assignments" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "capstone_module_assignments",
            sa.Column("class_id", sa.Uuid(), nullable=False),
            sa.Column("student_user_id", sa.Uuid(), nullable=False),
            sa.Column("module_name", sa.Unicode(120), nullable=False),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["class_id"], ["teaching_classes.id"]),
            sa.ForeignKeyConstraint(["student_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("class_id", "student_user_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "capstone_module_assignments" in sa.inspect(bind).get_table_names():
        op.drop_table("capstone_module_assignments")
