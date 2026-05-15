"""initial

Revision ID: b2010f0c8f94
Revises: 
Create Date: 2026-05-15 13:21:34.615332

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2010f0c8f94'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'admin_user',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('salt', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'orgs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), unique=True, nullable=False),
    )
    op.create_table(
        'sites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=True),
    )
    op.create_table(
        'check_results',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('site_id', sa.Integer(), sa.ForeignKey('sites.id'), nullable=False, index=True),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False, index=True),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('response_time_ms', sa.Float(), nullable=False),
        sa.Column('is_up', sa.Boolean(), nullable=False),
    )
    op.create_table(
        'site_status',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('scope_id', sa.Integer(), nullable=False),
        sa.Column('status_type', sa.String(), nullable=False),
        sa.Column('message', sa.String(), nullable=False),
        sa.Column('updates', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('site_status')
    op.drop_table('check_results')
    op.drop_table('sites')
    op.drop_table('orgs')
    op.drop_table('admin_user')
