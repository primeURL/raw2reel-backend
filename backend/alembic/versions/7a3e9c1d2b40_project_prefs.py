"""project prefs: the creator's own choices (caption look, sounds, transitions, effects)

Revision ID: 7a3e9c1d2b40
Revises: 299678d9d4cb
Create Date: 2026-11-22 20:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7a3e9c1d2b40'
down_revision: Union[str, None] = '299678d9d4cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('prefs', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'prefs')
