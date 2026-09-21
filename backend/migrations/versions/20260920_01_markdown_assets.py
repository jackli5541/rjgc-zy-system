"""Store Markdown images separately from document text.

Revision ID: 20260920_01
Revises: 20260919_05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260920_01"
down_revision = "20260919_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "markdown_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("storage_path", sa.Unicode(255), nullable=False),
        sa.Column("original_name", sa.Unicode(255), nullable=False),
        sa.Column("mime_type", sa.Unicode(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Unicode(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("orphaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["submission_workspaces.id"]),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_path"),
    )
    op.create_index("ix_markdown_assets_assignment_id", "markdown_assets", ["assignment_id"])
    op.create_index("ix_markdown_assets_workspace_id", "markdown_assets", ["workspace_id"])
    op.create_index("ix_markdown_assets_uploader_id", "markdown_assets", ["uploader_id"])
    op.create_index("ix_markdown_assets_orphaned_at", "markdown_assets", ["orphaned_at"])
    op.create_table(
        "submission_document_assets",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["submission_documents.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["markdown_assets.id"]),
        sa.PrimaryKeyConstraint("document_id", "asset_id"),
    )
    op.create_index("ix_submission_document_assets_asset_id", "submission_document_assets", ["asset_id"])
    op.create_table(
        "file_object_assets",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["file_objects.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["markdown_assets.id"]),
        sa.PrimaryKeyConstraint("file_id", "asset_id"),
    )
    op.create_index("ix_file_object_assets_asset_id", "file_object_assets", ["asset_id"])


def downgrade() -> None:
    op.drop_table("file_object_assets")
    op.drop_table("submission_document_assets")
    op.drop_table("markdown_assets")
