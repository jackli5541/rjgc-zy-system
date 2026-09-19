"""Add class-scoped teaching material folders and files."""

import sqlalchemy as sa
from alembic import op


revision = "20260919_03"
down_revision = "20260919_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    from app.models import TeachingMaterial, TeachingMaterialFolder

    TeachingMaterialFolder.__table__.create(bind=bind, checkfirst=True)
    TeachingMaterial.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    from app.models import TeachingMaterial, TeachingMaterialFolder

    TeachingMaterial.__table__.drop(bind=bind, checkfirst=True)
    TeachingMaterialFolder.__table__.drop(bind=bind, checkfirst=True)
