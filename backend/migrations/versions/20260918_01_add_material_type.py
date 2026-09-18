"""Add material_type to file_objects for assignment material classification."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_01"
down_revision = "20260917_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("file_objects", sa.Column("material_type", sa.Unicode(16), nullable=True))
    op.execute("UPDATE file_objects SET material_type = 'ATTACHMENT' WHERE purpose = 'ATTACHMENT'")


def downgrade() -> None:
    op.drop_column("file_objects", "material_type")
