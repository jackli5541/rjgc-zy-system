"""Add material_type to file_objects for assignment material classification."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_03"
down_revision = "20260918_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("file_objects")}
    if "material_type" not in columns:
        op.add_column("file_objects", sa.Column("material_type", sa.Unicode(16), nullable=True))
    op.execute("UPDATE file_objects SET material_type = 'ATTACHMENT' WHERE purpose = 'ATTACHMENT' AND material_type IS NULL")


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("file_objects")}
    if "material_type" in columns:
        op.drop_column("file_objects", "material_type")
