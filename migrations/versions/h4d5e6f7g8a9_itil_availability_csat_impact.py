"""ITIL 增强 K-N：真实可用率采集、CSAT、变更影响分析、事件分组工单

Revision ID: h4d5e6f7g8a9
Revises: g3b4c5d6e7f8
Create Date: 2026-07-27

新增/调整：
- availability_records 表 (对接 DeviceMonitorLog 的真实可用率)
- service_catalog_devices 表 (服务目录<->设备 映射，用于服务级可用率与影响聚合)
- csat_surveys 表 (服务目录级客户满意度)
- change_impact_analyses 表 (变更影响模拟快照)
- event_correlation_rules.auto_ticket (分组时自动生成单一事件工单)
- work_orders.correlation_group / auto_created (关联分组与自动生成标记)
"""
from alembic import op
import sqlalchemy as sa

revision = 'h4d5e6f7g8a9'
down_revision = 'g3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade():
    # event_correlation_rules: 自动工单开关
    with op.batch_alter_table('event_correlation_rules') as batch_op:
        batch_op.add_column(sa.Column('auto_ticket', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))

    # work_orders: 关联分组与自动生成标记
    with op.batch_alter_table('work_orders') as batch_op:
        batch_op.add_column(sa.Column('correlation_group', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('auto_created', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
        batch_op.create_index('idx_work_order_correlation', ['correlation_group'])

    # availability_records 表
    op.create_table('availability_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('device_id', sa.Integer(), sa.ForeignKey('devices.id'), nullable=True),
        sa.Column('service_catalog_id', sa.Integer(), sa.ForeignKey('service_catalogs.id'), nullable=True),
        sa.Column('period_start', sa.DateTime(), nullable=False),
        sa.Column('period_end', sa.DateTime(), nullable=False),
        sa.Column('total_minutes', sa.Float(), nullable=False),
        sa.Column('down_minutes', sa.Float(), nullable=True),
        sa.Column('availability_pct', sa.Float(), nullable=False),
        sa.Column('incident_count', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id']),
        sa.ForeignKeyConstraint(['service_catalog_id'], ['service_catalogs.id']),
        sa.Index('ix_availability_device', 'device_id'),
        sa.Index('ix_availability_service', 'service_catalog_id'),
    )

    # service_catalog_devices 关联表
    op.create_table('service_catalog_devices',
        sa.Column('service_catalog_id', sa.Integer(), sa.ForeignKey('service_catalogs.id'), primary_key=True, nullable=False),
        sa.Column('device_id', sa.Integer(), sa.ForeignKey('devices.id'), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(['service_catalog_id'], ['service_catalogs.id']),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id']),
    )

    # csat_surveys 表
    op.create_table('csat_surveys',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('service_catalog_id', sa.Integer(), sa.ForeignKey('service_catalogs.id'), nullable=True),
        sa.Column('work_order_id', sa.Integer(), sa.ForeignKey('work_orders.id'), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('channel', sa.String(length=20), nullable=True),
        sa.Column('respondent', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['service_catalog_id'], ['service_catalogs.id']),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id']),
        sa.Index('ix_csat_service', 'service_catalog_id'),
        sa.Index('ix_csat_work_order', 'work_order_id'),
    )

    # change_impact_analyses 表
    op.create_table('change_impact_analyses',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False),
        sa.Column('simulated_at', sa.DateTime(), nullable=True),
        sa.Column('direct_device_ids', sa.Text(), nullable=True),
        sa.Column('impacted_device_ids', sa.Text(), nullable=True),
        sa.Column('impacted_service_ids', sa.Text(), nullable=True),
        sa.Column('affected_user_count', sa.Integer(), nullable=True),
        sa.Column('downtime_estimate_min', sa.Float(), nullable=True),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('risk_level', sa.String(length=20), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['change_id'], ['change_requests.id']),
        sa.Index('ix_impact_change', 'change_id'),
    )


def downgrade():
    op.drop_table('change_impact_analyses')
    op.drop_table('csat_surveys')
    op.drop_table('service_catalog_devices')
    op.drop_table('availability_records')

    with op.batch_alter_table('work_orders') as batch_op:
        batch_op.drop_index('idx_work_order_correlation')
        batch_op.drop_column('auto_created')
        batch_op.drop_column('correlation_group')

    with op.batch_alter_table('event_correlation_rules') as batch_op:
        batch_op.drop_column('auto_ticket')
