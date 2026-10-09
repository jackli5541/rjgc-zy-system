"""Add a database default for peer feedback update timestamps."""

import sqlalchemy as sa
from alembic import op


revision = "20261007_05"
down_revision = "20261007_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "peer_assessment_feedbacks",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def downgrade() -> None:
    op.alter_column(
        "peer_assessment_feedbacks",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=None,
    )
