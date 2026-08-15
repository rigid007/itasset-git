"""add link aging and AP fields to connection_paths

Revision ID: i5e6f7g8h9a0
Revises: h4d5e6f7g8a9
Create Date: 2026-08-01

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'i5e6f7g8h9a0'
down_revision = 'h4d5e6f7g8a9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('connection_paths',
        sa.Column('last_seen', sa.DateTime(), nullable=True)
    )
    op.add_column('connection_paths',
        sa.Column('auto_discovered', sa.Boolean(), nullable=False,
                  server_default=sa.text('0'), default=False)
    )
    op.add_column('connection_paths',
        sa.Column('neighbor_managed', sa.Boolean(), nullable=False,
                  server_default=sa.text('1'), default=True)
    )
    op.add_column('connection_paths',
        sa.Column('link_role', sa.String(length=20), nullable=True,
                  server_default=sa.text("'normal'"))
    )
    op.create_index(op.f('ix_connection_paths_link_role'), 'connection_paths',
                    ['link_role'])
    op.create_index(op.f('ix_connection_paths_auto_discovered'), 'connection_paths',
                    ['auto_discovered'])


def downgrade():
    op.drop_index(op.f('ix_connection_paths_auto_discovered'), table_name='connection_paths')
    op.drop_index(op.f('ix_connection_paths_link_role'), table_name='connection_paths')
    op.drop_column('connection_paths', 'link_role')
    op.drop_column('connection_paths', 'neighbor_managed')
    op.drop_column('connection_paths', 'auto_discovered')
    op.drop_column('connection_paths', 'last_seen')
