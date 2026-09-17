"""SQL Server baseline schema.

This project had no production data when the previous database was retired,
so the legacy revision chain was intentionally replaced by this baseline.
"""

from alembic import op

from app.database import Base
from app.models import *  # noqa: F403

revision = "20260917_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mssql":
        raise RuntimeError("This schema supports SQL Server only.")
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
