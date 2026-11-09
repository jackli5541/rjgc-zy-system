"""Add token-authenticated agent access (MCP) tables."""

import sqlalchemy as sa
from alembic import op


revision = "20261109_01"
down_revision = "20261012_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "agent_tokens" not in tables:
        op.create_table(
            "agent_tokens",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.Unicode(80), nullable=False),
            sa.Column("prefix", sa.Unicode(16), nullable=False),
            sa.Column("token_hash", sa.Unicode(64), nullable=False),
            sa.Column("owner_user_id", sa.Uuid(), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("class_ids", sa.JSON(), nullable=False),
            sa.Column("assignment_ids", sa.JSON(), nullable=False),
            sa.Column("expose_real_name", sa.Boolean(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.Unicode(16), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index("ix_agent_tokens_prefix", "agent_tokens", ["prefix"])
        op.create_index("ix_agent_tokens_owner_user_id", "agent_tokens", ["owner_user_id"])
        op.create_index("ix_agent_tokens_status", "agent_tokens", ["status"])
    if "agent_claims" not in tables:
        op.create_table(
            "agent_claims",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("token_id", sa.Uuid(), nullable=False),
            sa.Column("assignment_id", sa.Uuid(), nullable=False),
            sa.Column("submission_version_id", sa.Uuid(), nullable=False),
            sa.Column("status", sa.Unicode(16), nullable=False),
            sa.Column("release_reason", sa.Unicode(200), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["token_id"], ["agent_tokens.id"]),
            sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["submission_version_id"], ["submission_versions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agent_claims_token_id", "agent_claims", ["token_id"])
        op.create_index("ix_agent_claims_assignment_id", "agent_claims", ["assignment_id"])
        op.create_index("ix_agent_claims_submission_version_id", "agent_claims", ["submission_version_id"])
        op.create_index("ix_agent_claims_lookup", "agent_claims", ["assignment_id", "submission_version_id", "status"])
    if "agent_call_logs" not in tables:
        op.create_table(
            "agent_call_logs",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("token_id", sa.Uuid(), nullable=True),
            sa.Column("tool", sa.Unicode(40), nullable=False),
            sa.Column("assignment_id", sa.Uuid(), nullable=True),
            sa.Column("status", sa.Unicode(16), nullable=False),
            sa.Column("error_code", sa.Unicode(60), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=False),
            sa.Column("ip_address", sa.Unicode(45), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["token_id"], ["agent_tokens.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agent_call_logs_token_id", "agent_call_logs", ["token_id"])
        op.create_index("ix_agent_call_logs_assignment_id", "agent_call_logs", ["assignment_id"])
        op.create_index("ix_agent_call_logs_created_at", "agent_call_logs", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("agent_call_logs", "agent_claims", "agent_tokens"):
        if name in tables:
            op.drop_table(name)
