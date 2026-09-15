"""Add file ownership scope and grade revision history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_02"
down_revision = "20260915_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    file_columns = {column["name"] for column in inspector.get_columns("file_objects")}
    if "team_id" not in file_columns:
        op.add_column("file_objects", sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index("ix_file_objects_team_id", "file_objects", ["team_id"])
        op.create_foreign_key("fk_file_objects_team_id", "file_objects", "teams", ["team_id"], ["id"])
    if "purpose" not in file_columns:
        op.add_column("file_objects", sa.Column("purpose", sa.String(length=16), nullable=False, server_default="SUBMISSION"))
    grade_constraints = {item["name"] for item in inspector.get_unique_constraints("grades")}
    if "uq_personal_grade" not in grade_constraints: op.create_unique_constraint("uq_personal_grade", "grades", ["assignment_id", "subject_user_id"])
    if "uq_team_grade" not in grade_constraints: op.create_unique_constraint("uq_team_grade", "grades", ["assignment_id", "subject_team_id"])
    if "grade_revisions" not in inspector.get_table_names():
        op.create_table(
            "grade_revisions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("grade_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["changed_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["grade_id"], ["grades.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_grade_revisions_grade_id", "grade_revisions", ["grade_id"])


def downgrade() -> None:
    op.drop_index("ix_grade_revisions_grade_id", table_name="grade_revisions")
    op.drop_table("grade_revisions")
    op.drop_constraint("uq_team_grade", "grades", type_="unique")
    op.drop_constraint("uq_personal_grade", "grades", type_="unique")
    op.drop_constraint("fk_file_objects_team_id", "file_objects", type_="foreignkey")
    op.drop_index("ix_file_objects_team_id", table_name="file_objects")
    op.drop_column("file_objects", "purpose")
    op.drop_column("file_objects", "team_id")
