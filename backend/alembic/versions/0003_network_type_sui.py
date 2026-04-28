"""network type for non-EVM chains

Revision ID: 0003_network_type_sui
Revises: 0002_performance_exports_diagrams
Create Date: 2026-04-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_network_type_sui"
down_revision = "0002_performance_exports_diagrams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("networks")}
    if "network_type" not in columns:
        op.add_column("networks", sa.Column("network_type", sa.String(length=32), nullable=False, server_default="evm"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("networks")}
    if "network_type" in columns:
        op.drop_column("networks", "network_type")
