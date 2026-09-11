"""add discovery candidate approval fields

Revision ID: m5n6o7p8q9r0
Revises: l3m4n5o6p7q8
Create Date: 2026-09-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'm5n6o7p8q9r0'
down_revision = 'l3m4n5o6p7q8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    def add_column(table, name, column):
        existing = {c['name'] for c in inspector.get_columns(table)}
        if name not in existing:
            op.add_column(table, column)

    add_column('devices', 'discovery_source', sa.Column('discovery_source', sa.String(length=32), nullable=True))
    add_column('devices', 'external_ref', sa.Column('external_ref', sa.String(length=255), nullable=True))
    add_column('devices', 'discovery_confidence', sa.Column('discovery_confidence', sa.Integer(), nullable=True, server_default=sa.text('100')))
    add_column('devices', 'approval_status', sa.Column('approval_status', sa.String(length=20), nullable=True, server_default=sa.text("'approved'")))
    add_column('devices', 'last_seen', sa.Column('last_seen', sa.DateTime(), nullable=True))
    add_column('devices', 'managed_by', sa.Column('managed_by', sa.String(length=32), nullable=True))

    add_column('discovery_results', 'match_device_id', sa.Column('match_device_id', sa.Integer(), nullable=True))
    add_column('discovery_results', 'match_score', sa.Column('match_score', sa.Integer(), nullable=True, server_default=sa.text('0')))
    add_column('discovery_results', 'decision', sa.Column('decision', sa.String(length=20), nullable=True))
    add_column('discovery_results', 'error_code', sa.Column('error_code', sa.String(length=50), nullable=True))
    add_column('discovery_results', 'error_message', sa.Column('error_message', sa.Text(), nullable=True))

    indexes = {idx['name'] for idx in inspector.get_indexes('devices')}
    index_name = op.f('ix_devices_approval_status')
    if index_name not in indexes:
        op.create_index(index_name, 'devices', ['approval_status'])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    devices_cols = {c['name'] for c in inspector.get_columns('devices')}
    result_cols = {c['name'] for c in inspector.get_columns('discovery_results')}
    devices_indexes = {idx['name'] for idx in inspector.get_indexes('devices')}

    index_name = op.f('ix_devices_approval_status')
    if index_name in devices_indexes:
        op.drop_index(index_name, table_name='devices')

    for col in ('error_message', 'error_code', 'decision', 'match_score', 'match_device_id'):
        if col in result_cols:
            op.drop_column('discovery_results', col)
    for col in ('managed_by', 'last_seen', 'approval_status', 'discovery_confidence', 'external_ref', 'discovery_source'):
        if col in devices_cols:
            op.drop_column('devices', col)
