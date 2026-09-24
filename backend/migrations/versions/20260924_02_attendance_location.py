"""Add location boundaries and out-of-range attendance attempts."""

import sqlalchemy as sa
from alembic import op


revision = "20260924_02"
down_revision = "20260924_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attendance_sessions", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("attendance_sessions", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("attendance_sessions", sa.Column("radius_meters", sa.Integer(), nullable=True))
    op.add_column("attendance_records", sa.Column("out_of_range_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("attendance_records", sa.Column("last_out_of_range_meters", sa.Integer(), nullable=True))
    op.add_column("attendance_records", sa.Column("last_out_of_range_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("attendance_records", "last_out_of_range_at")
    op.drop_column("attendance_records", "last_out_of_range_meters")
    op.drop_column("attendance_records", "out_of_range_attempts")
    op.drop_column("attendance_sessions", "radius_meters")
    op.drop_column("attendance_sessions", "longitude")
    op.drop_column("attendance_sessions", "latitude")
