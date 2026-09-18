"""Scope the team-name uniqueness to active teams only.

Previously a disbanded team's name permanently blocked reuse within the
same class, because the unique constraint covered every row regardless
of status. Replaced with a filtered unique index that only applies to
ACTIVE teams, matching the existing pattern used for submissions.
"""

from alembic import op

revision = "20260918_02"
down_revision = "20260918_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_team_name", "teams", type_="unique")
    op.execute("CREATE UNIQUE INDEX uq_team_name ON teams (class_id, normalized_name) WHERE status = 'ACTIVE'")


def downgrade() -> None:
    op.execute("DROP INDEX uq_team_name ON teams")
    op.create_unique_constraint("uq_team_name", "teams", ["class_id", "normalized_name"])
