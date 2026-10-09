"""Add draft lifecycle fields to teacher feedback on peer assessments."""

import sqlalchemy as sa
from alembic import op


revision = "20261007_03"
down_revision = "20261007_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("peer_assessment_feedbacks")}
    if "status" not in columns:
        op.add_column("peer_assessment_feedbacks", sa.Column("status", sa.Unicode(16), nullable=True))
        op.execute("UPDATE peer_assessment_feedbacks SET status = 'PUBLISHED' WHERE status IS NULL")
        op.alter_column("peer_assessment_feedbacks", "status", existing_type=sa.Unicode(16), nullable=False)
        op.create_index("ix_peer_assessment_feedbacks_status", "peer_assessment_feedbacks", ["status"])
    if "updated_at" not in columns:
        op.add_column("peer_assessment_feedbacks", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE peer_assessment_feedbacks SET updated_at = created_at WHERE updated_at IS NULL")
        op.alter_column("peer_assessment_feedbacks", "updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("peer_assessment_feedbacks")}
    if "updated_at" in columns:
        op.drop_column("peer_assessment_feedbacks", "updated_at")
    if "status" in columns:
        op.drop_index("ix_peer_assessment_feedbacks_status", table_name="peer_assessment_feedbacks")
        op.drop_column("peer_assessment_feedbacks", "status")
