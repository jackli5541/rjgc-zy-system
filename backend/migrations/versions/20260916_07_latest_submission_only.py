"""Keep only the latest submission state outside frozen reviews."""

from alembic import op

revision = "20260916_07"
down_revision = "20260916_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM version_files
        WHERE version_id IN (
            SELECT sv.id
            FROM submission_versions sv
            JOIN submissions s ON s.id = sv.submission_id
            WHERE sv.version_no <> s.current_version_no
              AND NOT EXISTS (
                  SELECT 1 FROM review_assignments ra
                  WHERE ra.submission_version_id = sv.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM peer_reviews pr
                  WHERE pr.submission_version_id = sv.id
              )
        )
        """
    )
    op.execute(
        """
        DELETE FROM submission_versions sv
        USING submissions s
        WHERE s.id = sv.submission_id
          AND sv.version_no <> s.current_version_no
          AND NOT EXISTS (
              SELECT 1 FROM review_assignments ra
              WHERE ra.submission_version_id = sv.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM peer_reviews pr
              WHERE pr.submission_version_id = sv.id
          )
        """
    )


def downgrade() -> None:
    pass
