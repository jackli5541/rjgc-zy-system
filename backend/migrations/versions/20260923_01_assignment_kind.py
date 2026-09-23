"""Add kind (ASSIGNMENT/EXPERIMENT) to assignments."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_01"
down_revision = "20260922_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("assignments")}
    if "kind" not in columns:
        op.add_column("assignments", sa.Column("kind", sa.Unicode(16), nullable=True))
    op.execute("UPDATE assignments SET kind = 'ASSIGNMENT' WHERE kind IS NULL")


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("assignments")}
    if "kind" in columns:
        op.drop_column("assignments", "kind")
