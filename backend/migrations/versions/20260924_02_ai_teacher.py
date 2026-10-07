"""Add AI teacher chat tables.

Revision ID: 20260924_02
Revises: 20260924_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260924_02"
down_revision = "20260924_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_teacher_knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("owner_team_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.Unicode(32), nullable=False),
        sa.Column("source_id", sa.Unicode(80), nullable=True),
        sa.Column("source_title", sa.Unicode(255), nullable=False),
        sa.Column("visibility", sa.Unicode(32), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.UnicodeText(), nullable=False),
        sa.Column("embedding", sa.UnicodeText(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.Unicode(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.ForeignKeyConstraint(["owner_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_knowledge_chunks_assignment_id", "ai_teacher_knowledge_chunks", ["assignment_id"])
    op.create_index("ix_ai_knowledge_chunks_owner_user_id", "ai_teacher_knowledge_chunks", ["owner_user_id"])
    op.create_index("ix_ai_knowledge_chunks_owner_team_id", "ai_teacher_knowledge_chunks", ["owner_team_id"])
    op.create_index("ix_ai_knowledge_chunks_content_hash", "ai_teacher_knowledge_chunks", ["content_hash"])
    op.create_index("ix_ai_chunks_assignment_visibility", "ai_teacher_knowledge_chunks", ["assignment_id", "visibility"])
    op.create_index("ix_ai_chunks_assignment_owner", "ai_teacher_knowledge_chunks", ["assignment_id", "owner_user_id", "owner_team_id"])

    op.create_table(
        "ai_teacher_chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Unicode(16), nullable=False),
        sa.Column("content", sa.UnicodeText(), nullable=False),
        sa.Column("contexts", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_chat_messages_assignment_id", "ai_teacher_chat_messages", ["assignment_id"])
    op.create_index("ix_ai_chat_messages_student_id", "ai_teacher_chat_messages", ["student_id"])
    op.create_index("ix_ai_chat_messages_created_at", "ai_teacher_chat_messages", ["created_at"])
    op.create_index("ix_ai_chat_assignment_student_created", "ai_teacher_chat_messages", ["assignment_id", "student_id", "created_at"])


def downgrade() -> None:
    op.drop_table("ai_teacher_chat_messages")
    op.drop_table("ai_teacher_knowledge_chunks")
