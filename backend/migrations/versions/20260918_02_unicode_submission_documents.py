"""Use Unicode columns for online Markdown documents.

Revision ID: 20260918_02
Revises: 20260918_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260918_02"
down_revision = "20260918_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_workspace_document_name", "submission_documents", type_="unique")
    op.alter_column("submission_documents", "name", existing_type=sa.String(255), type_=sa.Unicode(255), existing_nullable=False)
    op.alter_column("submission_documents", "content_html", existing_type=sa.Text(), type_=sa.UnicodeText(), existing_nullable=False)
    op.alter_column("submission_documents", "markdown_content", existing_type=sa.Text(), type_=sa.UnicodeText(), existing_nullable=False)
    op.create_unique_constraint("uq_workspace_document_name", "submission_documents", ["workspace_id", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_workspace_document_name", "submission_documents", type_="unique")
    op.alter_column("submission_documents", "markdown_content", existing_type=sa.UnicodeText(), type_=sa.Text(), existing_nullable=False)
    op.alter_column("submission_documents", "content_html", existing_type=sa.UnicodeText(), type_=sa.Text(), existing_nullable=False)
    op.alter_column("submission_documents", "name", existing_type=sa.Unicode(255), type_=sa.String(255), existing_nullable=False)
    op.create_unique_constraint("uq_workspace_document_name", "submission_documents", ["workspace_id", "name"])
