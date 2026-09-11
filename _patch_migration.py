from pathlib import Path
text = '''"""Add spare part stock fields and supplier relation.

Revision ID: w7x8y9z0a3b4
Revises: v6w7x8y9z0a2
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'w7x8y9z0a3b4'
down_revision = 'v6w7x8y9z0a2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('spare_parts', sa.Column('current_stock', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('spare_parts', sa.Column('min_stock_level', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('spare_parts', sa.Column('max_stock_level', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('spare_parts', sa.Column('supplier_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_spare_parts_supplier_id', 'spare_parts', 'suppliers', ['supplier_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_spare_parts_supplier_id', 'spare_parts', type_='foreignkey')
    op.drop_column('spare_parts', 'supplier_id')
    op.drop_column('spare_parts', 'max_stock_level')
    op.drop_column('spare_parts', 'min_stock_level')
    op.drop_column('spare_parts', 'current_stock')
'''
p=Path('migrations/versions/w7x8y9z0a3b4_add_spare_part_stock_fields.py')
p.write_text(text.replace('\n','\r\n'), encoding='utf-8')
print('migration written')
