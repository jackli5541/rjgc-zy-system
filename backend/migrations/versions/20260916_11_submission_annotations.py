"""Add versioned teacher feedback and submission annotations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_11"
down_revision = "20260916_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("submission_assessments")}
    if "status" not in columns:
        op.add_column("submission_assessments", sa.Column("status", sa.String(length=16), nullable=False, server_default="PUBLISHED"))
    if "version" not in columns:
        op.add_column("submission_assessments", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    if "published_at" not in columns:
        op.add_column("submission_assessments", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE submission_assessments SET published_at = updated_at")
    if "draft_payload" not in columns:
        op.add_column("submission_assessments", sa.Column("draft_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    checks = {constraint["name"] for constraint in inspector.get_check_constraints("submission_assessments")}
    if "ck_submission_assessment_status" not in checks:
        op.create_check_constraint("ck_submission_assessment_status", "submission_assessments", "status IN ('DRAFT', 'PUBLISHED')")

    if "submission_annotations" in inspector.get_table_names():
        annotation_columns = {column["name"] for column in inspector.get_columns("submission_annotations")}
        if "mark_type" not in annotation_columns:
            op.add_column("submission_annotations", sa.Column("mark_type", sa.String(length=20), nullable=False, server_default="COMMENT"))
            op.execute("UPDATE submission_annotations SET mark_type = CASE WHEN length(trim(comment)) > 0 THEN 'COMMENT' ELSE 'HIGHLIGHT' END")
        if "color" not in annotation_columns:
            op.add_column("submission_annotations", sa.Column("color", sa.String(length=10), nullable=False, server_default="YELLOW"))
        annotation_checks = {constraint["name"] for constraint in inspector.get_check_constraints("submission_annotations")}
        if "ck_submission_annotation_kind" not in annotation_checks:
            op.create_check_constraint("ck_submission_annotation_kind", "submission_annotations", "kind IN ('PDF_TEXT_OR_REGION', 'RICH_TEXT_RANGE')")
        if "ck_submission_annotation_mark_type" not in annotation_checks:
            op.create_check_constraint("ck_submission_annotation_mark_type", "submission_annotations", "mark_type IN ('HIGHLIGHT', 'UNDERLINE', 'STRIKETHROUGH', 'COMMENT')")
        if "ck_submission_annotation_color" not in annotation_checks:
            op.create_check_constraint("ck_submission_annotation_color", "submission_annotations", "color IN ('YELLOW', 'GREEN', 'RED', 'BLUE')")
        return
    op.create_table(
        "submission_annotations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("mark_type", sa.String(length=20), nullable=False, server_default="COMMENT"),
        sa.Column("color", sa.String(length=10), nullable=False, server_default="YELLOW"),
        sa.Column("anchor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('PDF_TEXT_OR_REGION', 'RICH_TEXT_RANGE')", name="ck_submission_annotation_kind"),
        sa.CheckConstraint("mark_type IN ('HIGHLIGHT', 'UNDERLINE', 'STRIKETHROUGH', 'COMMENT')", name="ck_submission_annotation_mark_type"),
        sa.CheckConstraint("color IN ('YELLOW', 'GREEN', 'RED', 'BLUE')", name="ck_submission_annotation_color"),
        sa.ForeignKeyConstraint(["assessment_id"], ["submission_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["submission_version_id", "file_id"],
            ["version_files.version_id", "version_files.file_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("assessment_id", "submission_version_id", "file_id", "author_id"):
        op.create_index(f"ix_submission_annotations_{column}", "submission_annotations", [column])


def downgrade() -> None:
    op.drop_table("submission_annotations")
    op.drop_constraint("ck_submission_assessment_status", "submission_assessments", type_="check")
    op.drop_column("submission_assessments", "published_at")
    op.drop_column("submission_assessments", "draft_payload")
    op.drop_column("submission_assessments", "version")
    op.drop_column("submission_assessments", "status")
