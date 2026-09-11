"""add BMC controller approval fields

Revision ID: p0q1r2s3t4u5
Revises: n6o7p8q9r0s1
Create Date: 2026-09-10

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'p0q1r2s3t4u5'
down_revision = 'n6o7p8q9r0s1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_controllers' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('bmc_controllers')}
    if 'approval_status' not in columns:
        op.add_column('bmc_controllers', sa.Column('approval_status', sa.String(length=16), nullable=True, server_default='approved'))
    if 'approved_at' not in columns:
        op.add_column('bmc_controllers', sa.Column('approved_at', sa.DateTime(), nullable=True))
    if 'approved_by' not in columns:
        op.add_column('bmc_controllers', sa.Column('approved_by', sa.String(length=64), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_controllers' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('bmc_controllers')}
    if 'approved_by' in columns:
        op.drop_column('bmc_controllers', 'approved_by')
    if 'approved_at' in columns:
        op.drop_column('bmc_controllers', 'approved_at')
    if 'approval_status' in columns:
        op.drop_column('bmc_controllers', 'approval_status')
