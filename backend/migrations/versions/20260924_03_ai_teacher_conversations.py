"""Align AI teacher tables and add conversation and subject knowledge storage.

Revision ID: 20260924_03
Revises: 20260924_02
"""

from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision = "20260924_03"
down_revision = "20260924_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for old, new in (("ai_chat_messages", "ai_teacher_chat_messages"), ("ai_knowledge_chunks", "ai_teacher_knowledge_chunks")):
        if old in tables and new not in tables:
            op.rename_table(old, new)
            tables.remove(old)
            tables.add(new)

    chat = "ai_teacher_chat_messages"
    if chat not in tables or "ai_teacher_knowledge_chunks" not in tables:
        raise RuntimeError("AI teacher tables are missing; inspect the database before applying this migration")
    chunk_columns = {item["name"] for item in sa.inspect(bind).get_columns("ai_teacher_knowledge_chunks")}
    if "embedding" not in chunk_columns:
        op.add_column("ai_teacher_knowledge_chunks", sa.Column("embedding", sa.UnicodeText(), nullable=True))
    if "metadata" not in chunk_columns:
        op.add_column("ai_teacher_knowledge_chunks", sa.Column("metadata", sa.JSON(), nullable=True))
    columns = {item["name"] for item in sa.inspect(bind).get_columns(chat)}
    if "conversation_id" not in columns:
        op.add_column(chat, sa.Column("conversation_id", sa.Uuid(), nullable=True))
    # Legacy messages remain in one readable conversation without changing their content.
    bind.execute(
        sa.text(f"UPDATE {chat} SET conversation_id = :legacy WHERE conversation_id IS NULL")
        .bindparams(sa.bindparam("legacy", type_=sa.Uuid())),
        {"legacy": UUID(int=0)},
    )
    op.alter_column(chat, "conversation_id", existing_type=sa.Uuid(), nullable=False)
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(chat)}
    if "ix_ai_teacher_chat_messages_conversation_id" not in indexes:
        op.create_index("ix_ai_teacher_chat_messages_conversation_id", chat, ["conversation_id"])

    if "ai_teacher_subject_knowledge" not in tables:
        op.create_table(
            "ai_teacher_subject_knowledge",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("class_id", sa.Uuid(), sa.ForeignKey("teaching_classes.id"), nullable=False),
            sa.Column("title", sa.Unicode(255), nullable=False),
            sa.Column("content", sa.UnicodeText(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_ai_teacher_subject_knowledge_class_id", "ai_teacher_subject_knowledge", ["class_id"])

    if "ai_teacher_knowledge_nodes" not in tables:
        op.create_table(
            "ai_teacher_knowledge_nodes",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("subject", sa.Unicode(80), nullable=False),
            sa.Column("key", sa.Unicode(120), nullable=False),
            sa.Column("title", sa.Unicode(255), nullable=False),
            sa.Column("summary", sa.UnicodeText(), nullable=False),
            sa.Column("content", sa.UnicodeText(), nullable=False),
            sa.Column("visibility", sa.Unicode(32), nullable=False),
            sa.Column("metadata", sa.UnicodeText(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if "ai_teacher_knowledge_edges" not in tables:
        op.create_table(
            "ai_teacher_knowledge_edges",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("source_node_id", sa.Uuid(), sa.ForeignKey("ai_teacher_knowledge_nodes.id"), nullable=False),
            sa.Column("target_node_id", sa.Uuid(), sa.ForeignKey("ai_teacher_knowledge_nodes.id"), nullable=False),
            sa.Column("relation", sa.Unicode(80), nullable=False),
            sa.Column("weight", sa.Integer(), nullable=False),
            sa.Column("metadata", sa.UnicodeText(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    # Knowledge nodes/edges may predate this revision; leave them intact.
    op.drop_table("ai_teacher_subject_knowledge")
    op.drop_index("ix_ai_teacher_chat_messages_conversation_id", table_name="ai_teacher_chat_messages")
    op.drop_column("ai_teacher_chat_messages", "conversation_id")
