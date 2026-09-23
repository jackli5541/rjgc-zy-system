"""Create capstone (大作业) module tables: config, unlocks, templates, documents, assets, stage grades.

Revision ID: 20260922_01
Revises: 20260921_02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_01"
down_revision = "20260921_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = sa.inspect(bind).get_table_names()

    if "capstone_configs" not in existing:
        op.create_table(
            "capstone_configs",
            sa.Column("class_id", sa.Uuid(), nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["class_id"], ["teaching_classes.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("class_id"),
        )

    if "capstone_unlocks" not in existing:
        op.create_table(
            "capstone_unlocks",
            sa.Column("class_id", sa.Uuid(), nullable=False),
            sa.Column("student_user_id", sa.Uuid(), nullable=False),
            sa.Column("unlocked_by", sa.Uuid(), nullable=False),
            sa.Column("unlocked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["class_id"], ["teaching_classes.id"]),
            sa.ForeignKeyConstraint(["student_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["unlocked_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("class_id", "student_user_id"),
        )

    if "capstone_document_templates" not in existing:
        op.create_table(
            "capstone_document_templates",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("class_id", sa.Uuid(), nullable=False),
            sa.Column("stage", sa.Unicode(16), nullable=False),
            sa.Column("name", sa.Unicode(100), nullable=False),
            sa.Column("markdown_content", sa.UnicodeText(), nullable=False),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["class_id"], ["teaching_classes.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("class_id", "stage", name="uq_capstone_template_class_stage"),
        )
        op.create_index("ix_capstone_document_templates_class_id", "capstone_document_templates", ["class_id"])

    if "capstone_documents" not in existing:
        op.create_table(
            "capstone_documents",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("class_id", sa.Uuid(), nullable=False),
            sa.Column("student_user_id", sa.Uuid(), nullable=False),
            sa.Column("stage", sa.Unicode(16), nullable=False),
            sa.Column("name", sa.Unicode(120), nullable=False),
            sa.Column("markdown_content", sa.UnicodeText(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("template_id", sa.Uuid(), nullable=True),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["class_id"], ["teaching_classes.id"]),
            sa.ForeignKeyConstraint(["student_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["template_id"], ["capstone_document_templates.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_capstone_documents_class_id", "capstone_documents", ["class_id"])
        op.create_index("ix_capstone_documents_student_user_id", "capstone_documents", ["student_user_id"])

    if "capstone_assets" not in existing:
        op.create_table(
            "capstone_assets",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("document_id", sa.Uuid(), nullable=False),
            sa.Column("uploader_id", sa.Uuid(), nullable=False),
            sa.Column("storage_path", sa.Unicode(255), nullable=False),
            sa.Column("original_name", sa.Unicode(255), nullable=False),
            sa.Column("mime_type", sa.Unicode(100), nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("sha256", sa.Unicode(64), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["capstone_documents.id"]),
            sa.ForeignKeyConstraint(["uploader_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("storage_path"),
        )
        op.create_index("ix_capstone_assets_document_id", "capstone_assets", ["document_id"])

    if "capstone_stage_grades" not in existing:
        op.create_table(
            "capstone_stage_grades",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("class_id", sa.Uuid(), nullable=False),
            sa.Column("student_user_id", sa.Uuid(), nullable=False),
            sa.Column("stage", sa.Unicode(16), nullable=False),
            sa.Column("score", sa.Numeric(5, 2), nullable=True),
            sa.Column("comment", sa.UnicodeText(), nullable=False, server_default=""),
            sa.Column("graded_by", sa.Uuid(), nullable=True),
            sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["class_id"], ["teaching_classes.id"]),
            sa.ForeignKeyConstraint(["student_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["graded_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("class_id", "student_user_id", "stage", name="uq_capstone_grade"),
        )
        op.create_index("ix_capstone_stage_grades_class_id", "capstone_stage_grades", ["class_id"])
        op.create_index("ix_capstone_stage_grades_student_user_id", "capstone_stage_grades", ["student_user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    existing = sa.inspect(bind).get_table_names()
    for table in ("capstone_stage_grades", "capstone_assets", "capstone_documents", "capstone_document_templates", "capstone_unlocks", "capstone_configs"):
        if table in existing:
            op.drop_table(table)
