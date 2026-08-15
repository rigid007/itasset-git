"""add device group models

Revision ID: b1c3d5e7f9a0
Revises: a51224952b61
Create Date: 2026-07-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b1c3d5e7f9a0'
down_revision = 'a51224952b61'
branch_labels = None
depends_on = None


def upgrade():
    # 创建设备分组表
    op.create_table('device_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False, index=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('color', sa.String(length=20), nullable=True, server_default='#007bff'),
        sa.Column('icon', sa.String(length=50), nullable=True, server_default='fa-folder'),
        sa.Column('sort_order', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('device_groups.id', ondelete='SET NULL'), nullable=True),
        sa.Column('auto_rule_type', sa.String(length=20), nullable=True),
        sa.Column('auto_rule_value', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # 创建设备-分组多对多关联表
    op.create_table('device_group_members',
        sa.Column('device_id', sa.Integer(), sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('device_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('device_id', 'group_id')
    )


def downgrade():
    op.drop_table('device_group_members')
    op.drop_table('device_groups')
