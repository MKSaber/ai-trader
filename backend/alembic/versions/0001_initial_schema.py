"""Initial LSE Pattern Lab schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""

from typing import Sequence, Union

from alembic import op

from app.db.base import Base
from app.db import models  # noqa: F401

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all ORM tables."""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop all ORM tables."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
