"""add BMC connection settings

Revision ID: r2s3t4u5v6
Revises: q1r2s3t4u5
Create Date: 2026-09-10

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'r2s3t4u5v6'
down_revision = 'q1r2s3t4u5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_controllers' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('bmc_controllers')}
    if 'bmc_port' not in columns:
        op.add_column('bmc_controllers', sa.Column('bmc_port', sa.Integer(), nullable=True, server_default='443'))
    if 'use_ssl' not in columns:
        op.add_column('bmc_controllers', sa.Column('use_ssl', sa.Boolean(), nullable=True, server_default=sa.true()))
    if 'verify_ssl' not in columns:
        op.add_column('bmc_controllers', sa.Column('verify_ssl', sa.Boolean(), nullable=True, server_default=sa.false()))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_controllers' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('bmc_controllers')}
    if 'verify_ssl' in columns:
        op.drop_column('bmc_controllers', 'verify_ssl')
    if 'use_ssl' in columns:
        op.drop_column('bmc_controllers', 'use_ssl')
    if 'bmc_port' in columns:
        op.drop_column('bmc_controllers', 'bmc_port')
