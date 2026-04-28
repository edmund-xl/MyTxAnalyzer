"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op

from app.core.database import Base
from app.models import db  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
