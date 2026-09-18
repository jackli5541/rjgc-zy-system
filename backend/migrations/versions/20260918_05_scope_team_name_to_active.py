"""Scope the team-name uniqueness to active teams only."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_05"
down_revision = "20260918_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    index_kind = bind.execute(sa.text("""
        SELECT CASE WHEN i.is_unique_constraint = 1 THEN 'constraint' ELSE 'index' END
        FROM sys.indexes i
        WHERE i.object_id = OBJECT_ID(N'teams') AND i.name = N'uq_team_name'
    """)).scalar()
    if index_kind == "constraint":
        op.drop_constraint("uq_team_name", "teams", type_="unique")
    elif index_kind == "index":
        op.execute("DROP INDEX uq_team_name ON teams")
    if index_kind != "index" or not bind.execute(sa.text("""
        SELECT 1 FROM sys.indexes i
        WHERE i.object_id = OBJECT_ID(N'teams') AND i.name = N'uq_team_name'
          AND i.has_filter = 1
    """)).scalar():
        op.execute("CREATE UNIQUE INDEX uq_team_name ON teams (class_id, normalized_name) WHERE status = 'ACTIVE'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_team_name ON teams")
    op.create_unique_constraint("uq_team_name", "teams", ["class_id", "normalized_name"])
