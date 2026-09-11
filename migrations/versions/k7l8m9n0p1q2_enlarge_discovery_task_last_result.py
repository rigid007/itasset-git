"""enlarge discovery_tasks.last_result to MEDIUMTEXT

Revision ID: k7l8m9n0p1q2
Revises: j6f7g8h9a0b1
Create Date: 2026-08-15

原因：/24 网段 SNMP 扫描完成后会向 last_result 写入数百条设备结果，
JSON 体积可达 80-100KB，超过 MySQL TEXT 的 65535 字节上限，
导致最终 UPDATE 失败、发现任务卡在“运行中”。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import MEDIUMTEXT

# revision identifiers, used by Alembic.
revision = 'k7l8m9n0p1q2'
down_revision = 'j6f7g8h9a0b1'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'discovery_tasks',
        'last_result',
        existing_type=sa.Text(),
        type_=MEDIUMTEXT(),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        'discovery_tasks',
        'last_result',
        existing_type=MEDIUMTEXT(),
        type_=sa.Text(),
        existing_nullable=True,
    )
