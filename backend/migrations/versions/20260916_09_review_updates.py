"""Allow students to update reviews before the campaign deadline."""

from alembic import op

revision = "20260916_09"
down_revision = "20260916_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE review_campaigns SET allow_update = TRUE")


def downgrade() -> None:
    op.execute("UPDATE review_campaigns SET allow_update = FALSE")
