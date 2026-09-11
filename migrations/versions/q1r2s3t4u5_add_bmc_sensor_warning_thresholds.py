"""add BMC sensor warning thresholds

Revision ID: q1r2s3t4u5
Revises: p0q1r2s3t4u5
Create Date: 2026-09-10

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'q1r2s3t4u5'
down_revision = 'p0q1r2s3t4u5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_sensors' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('bmc_sensors')}
    if 'lower_warning' not in columns:
        op.add_column('bmc_sensors', sa.Column('lower_warning', sa.Float(), nullable=True))
    if 'upper_warning' not in columns:
        op.add_column('bmc_sensors', sa.Column('upper_warning', sa.Float(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bmc_sensors' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('bmc_sensors')}
    if 'upper_warning' in columns:
        op.drop_column('bmc_sensors', 'upper_warning')
    if 'lower_warning' in columns:
        op.drop_column('bmc_sensors', 'lower_warning')
