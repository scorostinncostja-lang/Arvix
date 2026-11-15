"""init

Revision ID: 7c6d88df0e8c
Revises: 
Create Date: 2026-09-12 13:12:02.944296

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '7c6d88df0e8c'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
