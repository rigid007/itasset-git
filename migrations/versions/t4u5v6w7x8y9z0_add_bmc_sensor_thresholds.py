"""add BMC sensor threshold overrides

Revision ID: t4u5v6w7x8y9z0
Revises: s3t4u5v6w7x8
Create Date: 2026-09-10

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 't4u5v6w7x8y9z0'
down_revision = 's3t4u5v6w7x8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_sensor_thresholds' in inspector.get_table_names():
        return
    op.create_table(
        'bmc_sensor_thresholds',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('controller_id', sa.Integer(), sa.ForeignKey('bmc_controllers.id'), nullable=True),
        sa.Column('name', sa.String(length=128), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=True),
        sa.Column('lower_warning', sa.Float(), nullable=True),
        sa.Column('upper_warning', sa.Float(), nullable=True),
        sa.Column('lower_critical', sa.Float(), nullable=True),
        sa.Column('upper_critical', sa.Float(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_bmc_sensor_threshold_lookup',
                    'bmc_sensor_thresholds',
                    ['controller_id', 'kind', 'name', 'enabled'])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_sensor_thresholds' not in inspector.get_table_names():
        return
    op.drop_index('idx_bmc_sensor_threshold_lookup', table_name='bmc_sensor_thresholds')
    op.drop_table('bmc_sensor_thresholds')
