"""create activity_logs

Revision ID: a51224952b61
Revises: d77d2c74533e
Create Date: 2025-01-01 00:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'a51224952b61'
down_revision = 'd77d2c74533e'
branch_labels = None
depends_on = None

def upgrade():
    # 仅创建新表，不删除任何表！
    op.create_table('activity_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False, default=sa.func.now()),
        sa.Column('type', sa.String(length=50), nullable=True),
        sa.Column('device_type', sa.String(length=50), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('status_color', sa.String(length=20), nullable=True),
        sa.Column('user', sa.String(length=100), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        mysql_collate='utf8mb4_general_ci'
    )

def downgrade():
    # 回滚时才删除这张新表
    op.drop_table('activity_logs')
