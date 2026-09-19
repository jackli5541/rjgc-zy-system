"""Add class-scoped teaching material folders and files and repair the prior branch."""

import sqlalchemy as sa
from alembic import op


revision = "20260919_04"
down_revision = "20260919_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    from app.models import TeachingMaterial, TeachingMaterialFolder

    TeachingMaterialFolder.__table__.create(bind=bind, checkfirst=True)
    TeachingMaterial.__table__.create(bind=bind, checkfirst=True)
    # The two original 20260919_03 migrations shared a revision id. Existing
    # databases may therefore have recorded the revision without adding this
    # column; repair it idempotently while making the history linear.
    if "grade_cap" not in {column["name"] for column in sa.inspect(bind).get_columns("submission_versions")}:
        op.add_column("submission_versions", sa.Column("grade_cap", sa.String(length=1), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    from app.models import TeachingMaterial, TeachingMaterialFolder

    TeachingMaterial.__table__.drop(bind=bind, checkfirst=True)
    TeachingMaterialFolder.__table__.drop(bind=bind, checkfirst=True)
