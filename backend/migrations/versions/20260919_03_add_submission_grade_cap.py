"""Add the submission version grade cap column."""
from alembic import op
import sqlalchemy as sa

revision = "20260919_03"
down_revision = "20260919_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "grade_cap" not in {column["name"] for column in sa.inspect(bind).get_columns("submission_versions")}:
        op.add_column("submission_versions", sa.Column("grade_cap", sa.String(length=1), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "grade_cap" in {column["name"] for column in sa.inspect(bind).get_columns("submission_versions")}:
        op.drop_column("submission_versions", "grade_cap")
