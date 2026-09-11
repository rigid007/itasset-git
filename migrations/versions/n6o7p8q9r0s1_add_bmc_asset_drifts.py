"""add bmc asset drift table

Revision ID: n6o7p8q9r0s1
Revises: m5n6o7p8q9r0
Create Date: 2026-09-10

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'n6o7p8q9r0s1'
down_revision = 'm5n6o7p8q9r0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_asset_drifts' not in inspector.get_table_names():
        op.create_table(
            'bmc_asset_drifts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('controller_id', sa.Integer(), sa.ForeignKey('bmc_controllers.id'), nullable=False),
            sa.Column('device_id', sa.Integer(), sa.ForeignKey('devices.id'), nullable=True),
            sa.Column('field_name', sa.String(length=64), nullable=False),
            sa.Column('expected_value', sa.Text(), nullable=True),
            sa.Column('discovered_value', sa.Text(), nullable=True),
            sa.Column('severity', sa.String(length=16), nullable=True),
            sa.Column('status', sa.String(length=16), nullable=True),
            sa.Column('source', sa.String(length=32), nullable=True),
            sa.Column('check_time', sa.DateTime(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
            sa.Column('resolved_by', sa.String(length=64), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_bmc_asset_drifts_controller_id', 'bmc_asset_drifts', ['controller_id'])
        op.create_index('ix_bmc_asset_drifts_device_id', 'bmc_asset_drifts', ['device_id'])
        op.create_index('ix_bmc_asset_drifts_status', 'bmc_asset_drifts', ['status'])
        op.create_index('ix_bmc_asset_drifts_check_time', 'bmc_asset_drifts', ['check_time'])
        op.create_index('idx_bmc_asset_drift_ctrl_field', 'bmc_asset_drifts', ['controller_id', 'field_name', 'status'])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_asset_drifts' in inspector.get_table_names():
        op.drop_index('idx_bmc_asset_drift_ctrl_field', table_name='bmc_asset_drifts')
        op.drop_index('ix_bmc_asset_drifts_check_time', table_name='bmc_asset_drifts')
        op.drop_index('ix_bmc_asset_drifts_status', table_name='bmc_asset_drifts')
        op.drop_index('ix_bmc_asset_drifts_device_id', table_name='bmc_asset_drifts')
        op.drop_index('ix_bmc_asset_drifts_controller_id', table_name='bmc_asset_drifts')
        op.drop_table('bmc_asset_drifts')
