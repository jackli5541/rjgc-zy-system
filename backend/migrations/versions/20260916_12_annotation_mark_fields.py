"""Repair annotation mark fields for databases already migrated to revision 11."""

import sqlalchemy as sa
from alembic import op

revision = "20260916_12"
down_revision = "20260916_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "submission_annotations" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("submission_annotations")}
    if "mark_type" not in columns:
        op.add_column(
            "submission_annotations",
            sa.Column("mark_type", sa.String(length=20), nullable=False, server_default="COMMENT"),
        )
        op.execute(
            "UPDATE submission_annotations "
            "SET mark_type = CASE WHEN length(trim(comment)) > 0 THEN 'COMMENT' ELSE 'HIGHLIGHT' END"
        )
    if "color" not in columns:
        op.add_column(
            "submission_annotations",
            sa.Column("color", sa.String(length=10), nullable=False, server_default="YELLOW"),
        )

    checks = {constraint["name"] for constraint in sa.inspect(op.get_bind()).get_check_constraints("submission_annotations")}
    if "ck_submission_annotation_mark_type" not in checks:
        op.create_check_constraint(
            "ck_submission_annotation_mark_type",
            "submission_annotations",
            "mark_type IN ('HIGHLIGHT', 'UNDERLINE', 'STRIKETHROUGH', 'COMMENT')",
        )
    if "ck_submission_annotation_color" not in checks:
        op.create_check_constraint(
            "ck_submission_annotation_color",
            "submission_annotations",
            "color IN ('YELLOW', 'GREEN', 'RED', 'BLUE')",
        )


def downgrade() -> None:
    # Revision 11 now defines these fields; this repair migration is intentionally reversible as a no-op.
    pass
