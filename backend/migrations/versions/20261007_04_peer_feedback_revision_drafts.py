"""Add revision drafts for published peer-assessment feedback."""

import sqlalchemy as sa
from alembic import op


revision = "20261007_04"
down_revision = "20261007_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("peer_assessment_feedbacks")}
    if "draft_category" not in columns:
        op.add_column("peer_assessment_feedbacks", sa.Column("draft_category", sa.Unicode(32), nullable=True))
    if "draft_reason" not in columns:
        op.add_column("peer_assessment_feedbacks", sa.Column("draft_reason", sa.UnicodeText(), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("peer_assessment_feedbacks")}
    if "draft_reason" in columns:
        op.drop_column("peer_assessment_feedbacks", "draft_reason")
    if "draft_category" in columns:
        op.drop_column("peer_assessment_feedbacks", "draft_category")
