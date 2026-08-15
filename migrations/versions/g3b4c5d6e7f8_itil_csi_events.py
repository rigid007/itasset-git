"""ITIL 增强 G-J：KEDB/知识库联动、服务目录级SLA、CSI、事件关联规则

Revision ID: g3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-27

新增/调整：
- known_errors.knowledge_article_id 关联知识库
- service_catalogs.sla_policy_id 关联SLA策略
- work_orders.service_catalog_id 关联服务目录
- alert_events.suppressed / correlation_group 事件关联
- csi_improvements 表 (持续改进登记册)
- event_correlation_rules 表 (事件归一化/关联规则)
"""
from alembic import op
import sqlalchemy as sa

revision = 'g3b4c5d6e7f8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    # known_errors: 关联知识库文章
    with op.batch_alter_table('known_errors') as batch_op:
        batch_op.add_column(sa.Column('knowledge_article_id', sa.Integer(),
                                      sa.ForeignKey('knowledge_articles.id'), nullable=True))
        batch_op.create_foreign_key('fk_known_errors_kb', 'knowledge_articles',
                                    ['knowledge_article_id'], ['id'])

    # service_catalogs: 关联SLA策略
    with op.batch_alter_table('service_catalogs') as batch_op:
        batch_op.add_column(sa.Column('sla_policy_id', sa.Integer(),
                                      sa.ForeignKey('sla_policies.id'), nullable=True))
        batch_op.create_foreign_key('fk_service_catalogs_sla', 'sla_policies',
                                    ['sla_policy_id'], ['id'])

    # work_orders: 关联服务目录
    with op.batch_alter_table('work_orders') as batch_op:
        batch_op.add_column(sa.Column('service_catalog_id', sa.Integer(),
                                      sa.ForeignKey('service_catalogs.id'), nullable=True))
        batch_op.create_foreign_key('fk_work_orders_service', 'service_catalogs',
                                    ['service_catalog_id'], ['id'])

    # alert_events: 事件关联字段
    with op.batch_alter_table('alert_events') as batch_op:
        batch_op.add_column(sa.Column('suppressed', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('correlation_group', sa.String(length=100), nullable=True))
        batch_op.create_index('idx_alert_correlation_group', ['correlation_group'])

    # csi_improvements 表
    op.create_table('csi_improvements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(length=64), nullable=False, unique=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source_type', sa.String(length=30), nullable=True),
        sa.Column('source_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('priority', sa.String(length=20), nullable=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('target_metric', sa.String(length=100), nullable=True),
        sa.Column('baseline_value', sa.Float(), nullable=True),
        sa.Column('target_value', sa.Float(), nullable=True),
        sa.Column('actual_value', sa.Float(), nullable=True),
        sa.Column('expected_benefit', sa.Text(), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
    )

    # event_correlation_rules 表
    op.create_table('event_correlation_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('priority_order', sa.Integer(), nullable=True),
        sa.Column('match_scope', sa.String(length=30), nullable=True),
        sa.Column('match_operator', sa.String(length=20), nullable=True),
        sa.Column('match_value', sa.String(length=200), nullable=True),
        sa.Column('action', sa.String(length=30), nullable=True),
        sa.Column('group_by', sa.String(length=20), nullable=True),
        sa.Column('suppression_window_min', sa.Integer(), nullable=True),
        sa.Column('new_severity', sa.String(length=20), nullable=True),
        sa.Column('new_priority', sa.String(length=20), nullable=True),
        sa.Column('normalize_template', sa.String(length=200), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
    )


def downgrade():
    op.drop_table('event_correlation_rules')
    op.drop_table('csi_improvements')

    with op.batch_alter_table('alert_events') as batch_op:
        batch_op.drop_index('idx_alert_correlation_group')
        batch_op.drop_column('correlation_group')
        batch_op.drop_column('suppressed')

    with op.batch_alter_table('work_orders') as batch_op:
        batch_op.drop_constraint('fk_work_orders_service', type_='foreignkey')
        batch_op.drop_column('service_catalog_id')

    with op.batch_alter_table('service_catalogs') as batch_op:
        batch_op.drop_constraint('fk_service_catalogs_sla', type_='foreignkey')
        batch_op.drop_column('sla_policy_id')

    with op.batch_alter_table('known_errors') as batch_op:
        batch_op.drop_constraint('fk_known_errors_kb', type_='foreignkey')
        batch_op.drop_column('knowledge_article_id')
