"""Record the operator IP address in audit logs."""

import sqlalchemy as sa
from alembic import op

revision = "20260917_13"
down_revision = "20260916_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("ip_address", sa.String(length=45), nullable=True))
    op.create_index("ix_audit_logs_ip_address", "audit_logs", ["ip_address"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_ip_address", table_name="audit_logs")
    op.drop_column("audit_logs", "ip_address")
