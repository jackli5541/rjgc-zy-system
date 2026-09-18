"""Repair missing online Markdown workspace tables."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_04"
down_revision = "20260918_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("submission_workspaces"):
        op.create_table(
            "submission_workspaces",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("assignment_id", sa.Uuid(), nullable=False),
            sa.Column("owner_user_id", sa.Uuid(), nullable=True),
            sa.Column("owner_team_id", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["owner_team_id"], ["teams.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_submission_workspaces_assignment_id", "submission_workspaces", ["assignment_id"])
        op.create_index("ix_submission_workspaces_owner_user_id", "submission_workspaces", ["owner_user_id"])
        op.create_index("ix_submission_workspaces_owner_team_id", "submission_workspaces", ["owner_team_id"])
        op.create_index("uq_personal_submission_workspace", "submission_workspaces", ["assignment_id", "owner_user_id"], unique=True, mssql_where=sa.text("owner_user_id IS NOT NULL"))
        op.create_index("uq_team_submission_workspace", "submission_workspaces", ["assignment_id", "owner_team_id"], unique=True, mssql_where=sa.text("owner_team_id IS NOT NULL"))
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("submission_documents"):
        op.create_table(
            "submission_documents",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("source_file_id", sa.Uuid(), nullable=True),
            sa.Column("name", sa.Unicode(length=255), nullable=False),
            sa.Column("content_html", sa.UnicodeText(), nullable=False),
            sa.Column("markdown_content", sa.UnicodeText(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("updated_by", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["submission_workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_file_id"], ["file_objects.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "name", name="uq_workspace_document_name"),
        )
        op.create_index("ix_submission_documents_workspace_id", "submission_documents", ["workspace_id"])


def downgrade() -> None:
    pass
