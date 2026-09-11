"""add netflow_records (probe_id, received_at) composite index

Revision ID: v6w7x8y9z0a2
Revises: u5v6w7x8y9z0a1
Create Date: 2026-09-10

配合按采集器下钻 + 时间窗口的查询（stats / records / report / sessions），
避免每次只走单列索引后回表。
"""
from alembic import op
from sqlalchemy import inspect

revision = 'v6w7x8y9z0a2'
down_revision = 'u5v6w7x8y9z0a1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'netflow_records' not in inspector.get_table_names():
        return
    indexes = {i['name'] for i in inspector.get_indexes('netflow_records')}
    if 'idx_netflow_record_probe_time' not in indexes:
        op.create_index(
            'idx_netflow_record_probe_time',
            'netflow_records',
            ['probe_id', 'received_at'],
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'netflow_records' not in inspector.get_table_names():
        return
    indexes = {i['name'] for i in inspector.get_indexes('netflow_records')}
    if 'idx_netflow_record_probe_time' in indexes:
        op.drop_index('idx_netflow_record_probe_time', table_name='netflow_records')
