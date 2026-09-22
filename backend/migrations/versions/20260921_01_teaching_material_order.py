"""Add sort_order to teaching material folders and files for manual ordering.

Revision ID: 20260921_01
Revises: 20260920_01
"""

import sqlalchemy as sa
from alembic import op


revision = "20260921_01"
down_revision = "20260920_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    folder_columns = {column["name"] for column in sa.inspect(bind).get_columns("teaching_material_folders")}
    if "sort_order" not in folder_columns:
        op.add_column("teaching_material_folders", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    material_columns = {column["name"] for column in sa.inspect(bind).get_columns("teaching_materials")}
    if "sort_order" not in material_columns:
        op.add_column("teaching_materials", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        """
        WITH ranked AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY class_id, parent_id ORDER BY name, created_at
            ) - 1 AS rn
            FROM teaching_material_folders
        )
        UPDATE f SET sort_order = ranked.rn
        FROM teaching_material_folders f
        JOIN ranked ON ranked.id = f.id
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY class_id, folder_id ORDER BY original_name, created_at
            ) - 1 AS rn
            FROM teaching_materials
        )
        UPDATE m SET sort_order = ranked.rn
        FROM teaching_materials m
        JOIN ranked ON ranked.id = m.id
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    folder_columns = {column["name"] for column in sa.inspect(bind).get_columns("teaching_material_folders")}
    if "sort_order" in folder_columns:
        op.drop_column("teaching_material_folders", "sort_order")
    material_columns = {column["name"] for column in sa.inspect(bind).get_columns("teaching_materials")}
    if "sort_order" in material_columns:
        op.drop_column("teaching_materials", "sort_order")
