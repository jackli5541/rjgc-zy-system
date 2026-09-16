"""Generate grades from frozen one-to-one peer reviews."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_08"
down_revision = "20260916_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The application is still in development. Legacy free-choice campaigns and
    # manually entered grades cannot be converted without inventing score rules.
    op.execute("DELETE FROM review_campaigns WHERE assignment_snapshot_at IS NULL")
    inspector = sa.inspect(op.get_bind())
    grade_columns = {column["name"] for column in inspector.get_columns("grades")}
    campaign_columns = {column["name"] for column in inspector.get_columns("review_campaigns")}
    allocation_columns = {column["name"] for column in inspector.get_columns("review_assignments")}
    if (
        "grade_coefficients" in inspector.get_table_names()
        and "campaign_id" in grade_columns
        and "grades_generated_at" in campaign_columns
        and "participant_team_id" in allocation_columns
    ):
        return

    op.drop_table("grade_revisions")
    op.drop_table("grades")

    op.add_column("review_campaigns", sa.Column("grades_generated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("review_assignments", sa.Column("participant_team_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_review_assignments_participant_team", "review_assignments", "teams", ["participant_team_id"], ["id"])
    op.create_index("ix_review_assignments_participant_team_id", "review_assignments", ["participant_team_id"])
    op.execute(
        """
        UPDATE review_assignments ra
        SET participant_team_id = tm.team_id
        FROM review_campaigns rc, team_members tm
        WHERE rc.id = ra.campaign_id
          AND tm.class_id = rc.class_id
          AND tm.user_id = ra.reviewer_id
          AND tm.status = 'ACTIVE'
        """
    )

    op.create_table(
        "grade_coefficients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("published_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "team_id", name="uq_grade_coefficient_assignment_team"),
    )
    op.create_index("ix_grade_coefficients_assignment_id", "grade_coefficients", ["assignment_id"])
    op.create_index("ix_grade_coefficients_team_id", "grade_coefficients", ["team_id"])

    op.create_table(
        "grades",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coefficient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("peer_review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("peer_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("draft_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["review_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["coefficient_id"], ["grade_coefficients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["peer_review_id"], ["peer_reviews.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "subject_user_id", name="uq_personal_grade"),
        sa.UniqueConstraint("peer_review_id", name="uq_grade_peer_review"),
    )
    for column in ("assignment_id", "campaign_id", "subject_user_id", "coefficient_id"):
        op.create_index(f"ix_grades_{column}", "grades", [column])

    op.create_table(
        "grade_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grade_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("peer_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("coefficient", sa.Numeric(12, 2), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["grade_id"], ["grades.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_grade_revisions_grade_id", "grade_revisions", ["grade_id"])


def downgrade() -> None:
    op.drop_table("grade_revisions")
    op.drop_table("grades")
    op.drop_table("grade_coefficients")
    op.drop_index("ix_review_assignments_participant_team_id", table_name="review_assignments")
    op.drop_constraint("fk_review_assignments_participant_team", "review_assignments", type_="foreignkey")
    op.drop_column("review_assignments", "participant_team_id")
    op.drop_column("review_campaigns", "grades_generated_at")

    op.create_table(
        "grades",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="DRAFT"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["subject_team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "subject_user_id", name="uq_personal_grade"),
        sa.UniqueConstraint("assignment_id", "subject_team_id", name="uq_team_grade"),
    )
    op.create_index("ix_grades_assignment_id", "grades", ["assignment_id"])
    op.create_index("ix_grades_subject_user_id", "grades", ["subject_user_id"])
    op.create_index("ix_grades_subject_team_id", "grades", ["subject_team_id"])
    op.create_table(
        "grade_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grade_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["grade_id"], ["grades.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_grade_revisions_grade_id", "grade_revisions", ["grade_id"])
