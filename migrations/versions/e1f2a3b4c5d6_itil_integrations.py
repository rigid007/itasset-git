"""ITSM 集成增强：告警→工单、问题/变更关联CMDB、工单SLA计时

Revision ID: e1f2a3b4c5d6
Revises: c8d9e0f1a2b3
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 告警关联工单（打通监控→事件）
    op.add_column('alert_events',
                  sa.Column('work_order_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_alert_events_work_order', 'alert_events', 'work_orders',
                          ['work_order_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_alert_events_work_order_id', 'alert_events', ['work_order_id'])

    # 2. 问题关联配置项(CI)
    op.add_column('problem_records',
                  sa.Column('device_id', sa.Integer(), nullable=True))
    op.add_column('problem_records',
                  sa.Column('asset_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_problem_records_device', 'problem_records', 'devices',
                          ['device_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_problem_records_asset', 'problem_records', 'assets',
                          ['asset_id'], ['id'], ondelete='SET NULL')

    # 3. 变更影响设备关联表（支持影响分析）
    op.create_table('change_affected_devices',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('change_id', sa.Integer(), nullable=False),
                    sa.Column('device_id', sa.Integer(), nullable=False),
                    sa.Column('note', sa.Text(), nullable=True),
                    sa.ForeignKeyConstraint(['change_id'], ['change_requests.id'], ondelete='CASCADE'),
                    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_change_affected_devices_change_id', 'change_affected_devices', ['change_id'])
    op.create_index('ix_change_affected_devices_device_id', 'change_affected_devices', ['device_id'])

    # 4. 工单 SLA 字段（响应/解决合规与超时违约）
    op.add_column('work_orders',
                  sa.Column('sla_policy_id', sa.Integer(), nullable=True))
    op.add_column('work_orders',
                  sa.Column('sla_response_met', sa.Boolean(), nullable=True))
    op.add_column('work_orders',
                  sa.Column('sla_resolution_met', sa.Boolean(), nullable=True))
    op.add_column('work_orders',
                  sa.Column('sla_status', sa.String(length=20), nullable=False, server_default='pending'))
    op.add_column('work_orders',
                  sa.Column('breached_at', sa.DateTime(), nullable=True))
    op.create_foreign_key('fk_work_orders_sla_policy', 'work_orders', 'sla_policies',
                          ['sla_policy_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_work_orders_sla_policy', 'work_orders', type_='foreignkey')
    op.drop_column('work_orders', 'breached_at')
    op.drop_column('work_orders', 'sla_status')
    op.drop_column('work_orders', 'sla_resolution_met')
    op.drop_column('work_orders', 'sla_response_met')
    op.drop_column('work_orders', 'sla_policy_id')

    op.drop_table('change_affected_devices')

    op.drop_constraint('fk_problem_records_asset', 'problem_records', type_='foreignkey')
    op.drop_constraint('fk_problem_records_device', 'problem_records', type_='foreignkey')
    op.drop_column('problem_records', 'asset_id')
    op.drop_column('problem_records', 'device_id')

    op.drop_index('ix_alert_events_work_order_id', 'alert_events')
    op.drop_constraint('fk_alert_events_work_order', 'alert_events', type_='foreignkey')
    op.drop_column('alert_events', 'work_order_id')
