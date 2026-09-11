"""add BMC sensor alert debounce state

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6
Create Date: 2026-09-10

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 's3t4u5v6w7x8'
down_revision = 'r2s3t4u5v6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_sensor_alert_states' in inspector.get_table_names():
        return
    op.create_table(
        'bmc_sensor_alert_states',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('controller_id', sa.Integer(), sa.ForeignKey('bmc_controllers.id'), nullable=False),
        sa.Column('sensor_name', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('sensor_kind', sa.String(length=32), nullable=False, server_default='sensor'),
        sa.Column('normalized_status', sa.String(length=16), nullable=True, server_default='ok'),
        sa.Column('consecutive_strikes', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('alert_id', sa.Integer(), nullable=True),
        sa.Column('last_abnormal_at', sa.DateTime(), nullable=True),
        sa.Column('last_ok_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('controller_id', 'sensor_name', 'sensor_kind', name='uq_bmc_sensor_alert_state_ctrl_name_kind'),
    )
    op.create_index('idx_bmc_sensor_alert_state_ctrl', 'bmc_sensor_alert_states', ['controller_id'])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_sensor_alert_states' not in inspector.get_table_names():
        return
    op.drop_index('idx_bmc_sensor_alert_state_ctrl', table_name='bmc_sensor_alert_states')
    op.drop_table('bmc_sensor_alert_states')
