"""add is_decommissioned to devices

Revision ID: c8d9e0f1a2b3
Revises: b1c3d5e7f9a0
Create Date: 2026-07-24

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c8d9e0f1a2b3'
down_revision = 'b1c3d5e7f9a0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('devices',
        sa.Column('is_decommissioned', sa.Boolean(), nullable=False,
                  server_default=sa.text('0'), default=False)
    )
    op.create_index(op.f('ix_devices_is_decommissioned'), 'devices',
                    ['is_decommissioned'])


def downgrade():
    op.drop_index(op.f('ix_devices_is_decommissioned'), table_name='devices')
    op.drop_column('devices', 'is_decommissioned')
