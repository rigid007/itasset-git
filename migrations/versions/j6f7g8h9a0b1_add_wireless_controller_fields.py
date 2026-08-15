"""add wireless controller fields to devices

Revision ID: j6f7g8h9a0b1
Revises: i5e6f7g8h9a0
Create Date: 2026-08-01

为 Device 增加无线控制器(AC)标记与厂商字段，供 AC/CAPWAP 发现 AP 模块使用。
"""
from alembic import op
import sqlalchemy as sa

revision = 'j6f7g8h9a0b1'
down_revision = 'i5e6f7g8h9a0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('devices') as batch_op:
        batch_op.add_column(sa.Column('is_wireless_controller', sa.Boolean(),
                                      nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('controller_vendor', sa.String(length=32),
                                      nullable=True, server_default='auto'))


def downgrade():
    with op.batch_alter_table('devices') as batch_op:
        batch_op.drop_column('controller_vendor')
        batch_op.drop_column('is_wireless_controller')
