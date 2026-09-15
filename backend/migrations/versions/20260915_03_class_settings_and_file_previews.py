"""Add class invitation settings and derived file preview metadata."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_03"
down_revision = "20260915_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    class_columns = {column["name"] for column in inspector.get_columns("teaching_classes")}
    if "topic_public" not in class_columns:
        op.add_column("teaching_classes", sa.Column("topic_public", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "invite_requires_approval" not in class_columns:
        op.add_column("teaching_classes", sa.Column("invite_requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()))

    file_columns = {column["name"] for column in inspector.get_columns("file_objects")}
    if "preview_storage_path" not in file_columns:
        op.add_column("file_objects", sa.Column("preview_storage_path", sa.String(length=255), nullable=True))
    if "preview_error" not in file_columns:
        op.add_column("file_objects", sa.Column("preview_error", sa.String(length=500), nullable=True))

    if "class_join_requests" not in inspector.get_table_names():
        op.create_table(
            "class_join_requests",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["class_id"], ["teaching_classes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    indexes = {index["name"] for index in inspector.get_indexes("class_join_requests")}
    if "ix_class_join_requests_class_id" not in indexes:
        op.create_index("ix_class_join_requests_class_id", "class_join_requests", ["class_id"])
    if "ix_class_join_requests_user_id" not in indexes:
        op.create_index("ix_class_join_requests_user_id", "class_join_requests", ["user_id"])
    if "uq_pending_class_join_request" not in indexes:
        op.create_index("uq_pending_class_join_request", "class_join_requests", ["class_id", "user_id"], unique=True, postgresql_where=sa.text("status = 'PENDING'"))


def downgrade() -> None:
    op.drop_index("uq_pending_class_join_request", table_name="class_join_requests")
    op.drop_index("ix_class_join_requests_user_id", table_name="class_join_requests")
    op.drop_index("ix_class_join_requests_class_id", table_name="class_join_requests")
    op.drop_table("class_join_requests")
    op.drop_column("file_objects", "preview_error")
    op.drop_column("file_objects", "preview_storage_path")
    op.drop_column("teaching_classes", "invite_requires_approval")
    op.drop_column("teaching_classes", "topic_public")
