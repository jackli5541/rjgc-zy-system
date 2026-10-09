"""Add teacher feedback for peer-assessment content."""

import sqlalchemy as sa
from alembic import op


revision = "20261007_01"
down_revision = "20260924_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    notification_columns = {column["name"] for column in sa.inspect(bind).get_columns("notifications")}
    if "content" not in notification_columns:
        op.add_column("notifications", sa.Column("content", sa.UnicodeText(), nullable=True))
    if "peer_assessment_feedbacks" not in tables:
        op.create_table(
            "peer_assessment_feedbacks",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("assessment_id", sa.Uuid(), nullable=False),
            sa.Column("annotation_id", sa.Uuid(), nullable=True),
            sa.Column("target_type", sa.Unicode(16), nullable=False),
            sa.Column("category", sa.Unicode(32), nullable=False),
            sa.Column("reason", sa.UnicodeText(), nullable=False),
            sa.Column("teacher_id", sa.Uuid(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["assessment_id"], ["submission_assessments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["annotation_id"], ["submission_annotations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
        )
        op.create_index("ix_peer_assessment_feedbacks_assessment_id", "peer_assessment_feedbacks", ["assessment_id"])
        op.create_index("ix_peer_assessment_feedbacks_annotation_id", "peer_assessment_feedbacks", ["annotation_id"])
        op.create_index("ix_peer_assessment_feedbacks_teacher_id", "peer_assessment_feedbacks", ["teacher_id"])
        op.create_index("ix_peer_assessment_feedbacks_revoked_at", "peer_assessment_feedbacks", ["revoked_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if "peer_assessment_feedbacks" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("peer_assessment_feedbacks")
    notification_columns = {column["name"] for column in sa.inspect(bind).get_columns("notifications")}
    if "content" in notification_columns:
        op.drop_column("notifications", "content")
