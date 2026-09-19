"""Add role-level menu visibility settings."""

from alembic import op


revision = "20260919_05"
down_revision = "20260919_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    from app.models import RoleMenuPermission

    RoleMenuPermission.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    from app.models import RoleMenuPermission

    RoleMenuPermission.__table__.drop(bind=bind, checkfirst=True)
