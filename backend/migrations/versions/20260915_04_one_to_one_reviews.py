"""Add frozen one-to-one peer review allocations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_04"
down_revision = "20260915_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    campaign_columns = {column["name"] for column in inspector.get_columns("review_campaigns")}
    if "mode" not in campaign_columns: op.add_column("review_campaigns", sa.Column("mode", sa.String(length=16), nullable=True))
    if "criteria_text" not in campaign_columns: op.add_column("review_campaigns", sa.Column("criteria_text", sa.Text(), nullable=True))
    if "assignment_snapshot_at" not in campaign_columns: op.add_column("review_campaigns", sa.Column("assignment_snapshot_at", sa.DateTime(timezone=True), nullable=True))
    if "review_assignments" not in inspector.get_table_names():
        op.create_table(
            "review_assignments",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("reviewee_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("submission_version_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
            sa.Column("skip_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["campaign_id"], ["review_campaigns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["reviewee_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["submission_version_id"], ["submission_versions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("campaign_id", "reviewer_id", name="uq_review_assignment_reviewer"),
            sa.UniqueConstraint("campaign_id", "reviewee_id", name="uq_review_assignment_reviewee"),
        )
        op.create_index("ix_review_assignments_campaign_id", "review_assignments", ["campaign_id"])
        op.create_index("ix_review_assignments_reviewer_id", "review_assignments", ["reviewer_id"])
        op.create_index("ix_review_assignments_reviewee_id", "review_assignments", ["reviewee_id"])
    peer_columns = {column["name"] for column in inspector.get_columns("peer_reviews")}
    if "allocation_id" not in peer_columns:
        op.add_column("peer_reviews", sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_unique_constraint("uq_peer_review_allocation", "peer_reviews", ["allocation_id"])
        op.create_foreign_key("fk_peer_reviews_allocation_id", "peer_reviews", "review_assignments", ["allocation_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    op.drop_constraint("fk_peer_reviews_allocation_id", "peer_reviews", type_="foreignkey")
    op.drop_constraint("uq_peer_review_allocation", "peer_reviews", type_="unique")
    op.drop_column("peer_reviews", "allocation_id")
    op.drop_index("ix_review_assignments_reviewee_id", table_name="review_assignments")
    op.drop_index("ix_review_assignments_reviewer_id", table_name="review_assignments")
    op.drop_index("ix_review_assignments_campaign_id", table_name="review_assignments")
    op.drop_table("review_assignments")
    op.drop_column("review_campaigns", "assignment_snapshot_at")
    op.drop_column("review_campaigns", "criteria_text")
    op.drop_column("review_campaigns", "mode")
