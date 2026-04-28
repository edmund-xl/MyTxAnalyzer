"""performance indexes, diagrams, report exports

Revision ID: 0002_performance_exports_diagrams
Revises: 0001_initial
Create Date: 2026-04-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_performance_exports_diagrams"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    def create_index(name: str, table: str, columns: list[str]) -> None:
        existing = {index["name"] for index in inspector.get_indexes(table)}
        if name not in existing:
            op.create_index(name, table, columns)

    create_index("idx_cases_status_updated", "cases", ["status", "updated_at"])
    create_index("idx_cases_network_updated", "cases", ["network_key", "updated_at"])
    create_index("idx_cases_updated", "cases", ["updated_at"])
    create_index("idx_transactions_case_block", "transactions", ["case_id", "block_number"])
    create_index("idx_evidence_case_created", "evidence", ["case_id", "created_at"])
    create_index("idx_reports_case_version", "reports", ["case_id", "version"])
    create_index("idx_job_runs_case_created", "job_runs", ["case_id", "created_at"])

    if "diagram_specs" not in tables:
        op.create_table(
            "diagram_specs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("case_id", sa.String(length=36), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("report_id", sa.String(length=36), sa.ForeignKey("reports.id", ondelete="SET NULL")),
            sa.Column("diagram_type", sa.String(length=64), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("mermaid_source", sa.Text(), nullable=False),
            sa.Column("nodes_edges", sa.JSON(), nullable=False),
            sa.Column("evidence_ids", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.String(length=32), nullable=False),
            sa.Column("source_type", sa.Text(), nullable=False),
            sa.Column("object_path", sa.Text()),
            sa.Column("content_hash", sa.Text()),
            sa.Column("created_by", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("case_id", "diagram_type", name="uq_diagram_specs_case_type"),
        )
    create_index("idx_diagram_specs_case_type", "diagram_specs", ["case_id", "diagram_type"])
    create_index("idx_diagram_specs_report_type", "diagram_specs", ["report_id", "diagram_type"])

    if "report_exports" not in tables:
        op.create_table(
            "report_exports",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("report_id", sa.String(length=36), sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
            sa.Column("format", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("object_path", sa.Text()),
            sa.Column("content_hash", sa.Text()),
            sa.Column("error", sa.Text()),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("report_id", "format", name="uq_report_exports_report_format"),
        )
    create_index("idx_report_exports_report", "report_exports", ["report_id"])
    create_index("idx_report_exports_status", "report_exports", ["status"])


def downgrade() -> None:
    op.drop_index("idx_report_exports_status", table_name="report_exports")
    op.drop_index("idx_report_exports_report", table_name="report_exports")
    op.drop_table("report_exports")
    op.drop_index("idx_diagram_specs_report_type", table_name="diagram_specs")
    op.drop_index("idx_diagram_specs_case_type", table_name="diagram_specs")
    op.drop_table("diagram_specs")
    op.drop_index("idx_job_runs_case_created", table_name="job_runs")
    op.drop_index("idx_reports_case_version", table_name="reports")
    op.drop_index("idx_evidence_case_created", table_name="evidence")
    op.drop_index("idx_transactions_case_block", table_name="transactions")
    op.drop_index("idx_cases_updated", table_name="cases")
    op.drop_index("idx_cases_network_updated", table_name="cases")
    op.drop_index("idx_cases_status_updated", table_name="cases")
