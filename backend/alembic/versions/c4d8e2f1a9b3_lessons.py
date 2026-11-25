"""lessons: creator memory, learnt from revision requests

Revision ID: c4d8e2f1a9b3
Revises: 7a3e9c1d2b40
Create Date: 2026-11-25 22:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d8e2f1a9b3'
down_revision: Union[str, None] = '7a3e9c1d2b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lessons',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('text', sa.String(length=200), nullable=False),
        sa.Column('applies_to', sa.String(length=40), nullable=False),
        sa.Column('rule', sa.String(length=48), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('request', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lessons_user_id', 'lessons', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_lessons_user_id', table_name='lessons')
    op.drop_table('lessons')
