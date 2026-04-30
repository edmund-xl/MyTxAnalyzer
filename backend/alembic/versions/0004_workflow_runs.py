"""workflow runs

Revision ID: 0004_workflow_runs
Revises: 0003_network_type_sui
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_workflow_runs"
down_revision = "0003_network_type_sui"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "workflow_runs" not in tables:
        op.create_table(
            "workflow_runs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("case_id", sa.String(length=36), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workflow_id", sa.Text(), nullable=False),
            sa.Column("mode", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("ended_at", sa.DateTime(timezone=True)),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("workflow_id", name="uq_workflow_runs_workflow_id"),
        )
    existing = {index["name"] for index in inspector.get_indexes("workflow_runs")}
    if "idx_workflow_runs_case_created" not in existing:
        op.create_index("idx_workflow_runs_case_created", "workflow_runs", ["case_id", "created_at"])
    if "idx_workflow_runs_status" not in existing:
        op.create_index("idx_workflow_runs_status", "workflow_runs", ["status"])


def downgrade() -> None:
    op.drop_index("idx_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("idx_workflow_runs_case_created", table_name="workflow_runs")
    op.drop_table("workflow_runs")
