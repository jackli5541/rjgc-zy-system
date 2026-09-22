"""Store Markdown images embedded in teaching materials separately (mirrors markdown_assets).

Revision ID: 20260921_02
Revises: 20260921_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260921_02"
down_revision = "20260921_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "teaching_material_assets" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "teaching_material_assets",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("material_id", sa.Uuid(), nullable=False),
            sa.Column("storage_path", sa.Unicode(255), nullable=False),
            sa.Column("original_name", sa.Unicode(255), nullable=False),
            sa.Column("mime_type", sa.Unicode(100), nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("sha256", sa.Unicode(64), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["material_id"], ["teaching_materials.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("storage_path"),
        )
        op.create_index("ix_teaching_material_assets_material_id", "teaching_material_assets", ["material_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "teaching_material_assets" in sa.inspect(bind).get_table_names():
        op.drop_table("teaching_material_assets")
