"""Bridge an external schema revision already present in the shared database.

The AI teacher tables from this revision are outside this checkout. This
placeholder preserves their Alembic history without modifying those tables.
"""

revision = "20260923_03"
down_revision = "20260923_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
