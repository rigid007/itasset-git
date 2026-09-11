"""add BMC sensor threshold audit fields

Revision ID: u5v6w7x8y9z0a1
Revises: t4u5v6w7x8y9z0
Create Date: 2026-09-10

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'u5v6w7x8y9z0a1'
down_revision = 't4u5v6w7x8y9z0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_sensors' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('bmc_sensors')}
    if 'threshold_rule_id' not in columns:
        op.add_column('bmc_sensors', sa.Column('threshold_rule_id', sa.Integer(), nullable=True))
    if 'threshold_source' not in columns:
        op.add_column('bmc_sensors', sa.Column('threshold_source', sa.String(length=16), nullable=True))
    if 'threshold_breach' not in columns:
        op.add_column('bmc_sensors', sa.Column('threshold_breach', sa.String(length=24), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_sensors' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('bmc_sensors')}
    if 'threshold_breach' in columns:
        op.drop_column('bmc_sensors', 'threshold_breach')
    if 'threshold_source' in columns:
        op.drop_column('bmc_sensors', 'threshold_source')
    if 'threshold_rule_id' in columns:
        op.drop_column('bmc_sensors', 'threshold_rule_id')
