"""add server/hypervisor link verify fields to devices

Revision ID: l3m4n5o6p7q8
Revises: k7l8m9n0p1q2
Create Date: 2026-08-19

为服务器-交换机连接核对表新增字段：
- bmc_ip / bmc_mac：服务器 BMC（iLO/iDRAC/XCC 等带外管理）信息
- virtualization_type：虚拟化平台标识
- is_virtual_host：是否虚拟化宿主机
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'l3m4n5o6p7q8'
down_revision = 'k7l8m9n0p1q2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('devices')}

    def add_column(name, column):
        if name not in columns:
            op.add_column('devices', column)

    add_column('bmc_ip', sa.Column('bmc_ip', sa.String(length=45), nullable=True))
    add_column('bmc_mac', sa.Column('bmc_mac', sa.String(length=17), nullable=True))
    add_column('virtualization_type', sa.Column('virtualization_type', sa.String(length=32),
                                                nullable=True, server_default=sa.text("''")))
    add_column('is_virtual_host', sa.Column('is_virtual_host', sa.Boolean(),
                                            nullable=False, server_default=sa.text('0')))

    indexes = {idx['name'] for idx in inspector.get_indexes('devices')}
    index_name = op.f('ix_devices_is_virtual_host')
    if index_name not in indexes:
        op.create_index(index_name, 'devices', ['is_virtual_host'])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('devices')}
    indexes = {idx['name'] for idx in inspector.get_indexes('devices')}

    index_name = op.f('ix_devices_is_virtual_host')
    if index_name in indexes:
        op.drop_index(index_name, table_name='devices')
    for col in ('is_virtual_host', 'virtualization_type', 'bmc_mac', 'bmc_ip'):
        if col in columns:
            op.drop_column('devices', col)
