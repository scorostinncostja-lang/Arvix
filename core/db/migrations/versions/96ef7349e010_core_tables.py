"""core tables

Revision ID: 96ef7349e010
Revises: 7c6d88df0e8c
Create Date: 2026-09-12 17:17:03.458898

"""
from typing import Sequence, Union

from alembic import op

from core.db.models import Base

# revision identifiers, used by Alembic.
revision: str = '96ef7349e010'
down_revision: Union[str, Sequence[str], None] = '7c6d88df0e8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создаёт все таблицы шага 0.2 (events, profile, goals, traits, day_templates,
    tasks, directives, biometrics, devices, seasons + проекции state_*) прямо из
    ORM-метаданных core/db/models.py — это гарантирует, что схема БД и модели не
    разъедутся с самого первого дня. Следующие миграции — уже обычным
    autogenerate-диффом против живой БД."""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
