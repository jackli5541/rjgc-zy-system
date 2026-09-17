"""Record teaching class context in audit logs."""

import sqlalchemy as sa
from alembic import op

revision = "20260917_14"
down_revision = "20260917_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("class_id", sa.Uuid(), nullable=True))
    op.add_column("audit_logs", sa.Column("class_semester", sa.String(length=40), nullable=True))
    op.add_column("audit_logs", sa.Column("class_name", sa.String(length=100), nullable=True))
    op.create_index("ix_audit_logs_class_id", "audit_logs", ["class_id"])

    op.execute("""
        UPDATE audit_logs AS logs
        SET class_id = classes.id, class_semester = classes.semester, class_name = classes.name
        FROM teaching_classes AS classes
        WHERE logs.object_type = 'class' AND logs.object_id = CAST(classes.id AS VARCHAR)
    """)
    op.execute("""
        UPDATE audit_logs AS logs
        SET class_id = classes.id, class_semester = classes.semester, class_name = classes.name
        FROM assignments AS assignments, teaching_classes AS classes
        WHERE logs.object_type = 'assignment' AND logs.object_id = CAST(assignments.id AS VARCHAR) AND assignments.class_id = classes.id
    """)
    op.execute("""
        UPDATE audit_logs AS logs
        SET class_id = classes.id, class_semester = classes.semester, class_name = classes.name
        FROM teams AS teams, teaching_classes AS classes
        WHERE logs.object_type = 'team' AND logs.object_id = CAST(teams.id AS VARCHAR) AND teams.class_id = classes.id
    """)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_class_id", table_name="audit_logs")
    op.drop_column("audit_logs", "class_name")
    op.drop_column("audit_logs", "class_semester")
    op.drop_column("audit_logs", "class_id")
