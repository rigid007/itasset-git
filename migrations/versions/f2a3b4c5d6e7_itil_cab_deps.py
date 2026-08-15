"""ITIL 增强：CMDB 依赖关系 + CAB 审批链

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    # ---- ci_dependencies：CMDB 配置项依赖关系（有向图）----
    op.create_table(
        'ci_dependencies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('dependency_type', sa.String(length=30), nullable=False, server_default='depends_on'),
        sa.Column('criticality', sa.String(length=20), nullable=True, server_default='medium'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['devices.id'], ),
        sa.ForeignKeyConstraint(['target_id'], ['devices.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'target_id', 'dependency_type', name='uq_ci_dependency'),
    )
    op.create_index('ix_ci_dependencies_source_id', 'ci_dependencies', ['source_id'])
    op.create_index('ix_ci_dependencies_target_id', 'ci_dependencies', ['target_id'])

    # ---- change_approvals：变更审批链记录 ----
    op.create_table(
        'change_approvals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('change_id', sa.Integer(), nullable=False),
        sa.Column('stage', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('stage_name', sa.String(length=50), nullable=True),
        sa.Column('approver_id', sa.Integer(), nullable=True),
        sa.Column('approver_name', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('decided_by', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['change_id'], ['change_requests.id'], ),
        sa.ForeignKeyConstraint(['approver_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_change_approvals_change_id', 'change_approvals', ['change_id'])

    # ---- cab_config：CAB 审批阶段配置 ----
    op.create_table(
        'cab_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True, server_default='默认CAB'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column('stages_json', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('cab_config')
    op.drop_index('ix_change_approvals_change_id', table_name='change_approvals')
    op.drop_table('change_approvals')
    op.drop_index('ix_ci_dependencies_target_id', table_name='ci_dependencies')
    op.drop_index('ix_ci_dependencies_source_id', table_name='ci_dependencies')
    op.drop_table('ci_dependencies')
