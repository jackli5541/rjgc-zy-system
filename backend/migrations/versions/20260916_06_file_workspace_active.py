"""Track files in the current submission workspace."""

import sqlalchemy as sa
from alembic import op

revision = "20260916_06"
down_revision = "20260915_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("file_objects")}
    if "active" not in columns:
        op.add_column("file_objects", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("file_objects", "active")
