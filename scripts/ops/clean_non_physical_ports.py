"""
清理数据库中使用了非物理端口名的连接记录。
端口类型：Cellular*, Aux*, NULL*, Loopback*, Vlanif*, Tunnel*, Dialer*, Virtual*

用法：
  python clean_non_physical_ports.py --dry-run    # 仅预览
  python clean_non_physical_ports.py              # 实际删除
"""
import os
import sys
import re

# 使脚本可从任意目录运行（scripts/ops -> 项目根）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# 读取 .env 中的 DATABASE_URL
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('DATABASE_URL='):
                os.environ['DATABASE_URL'] = line.split('=', 1)[1].strip().strip('"').strip("'")
                break

from app import app
from models.models import db, ConnectionPath, Device

NON_PHYSICAL_PATTERNS = [
    r'^Cellular\d',
    r'^Aux\d',
    r'^NULL\d',
    r'^Loopback\d',
    r'^Vlanif\d',
    r'^Vlan-?Interface\d',
    r'^Tunnel\d',
    r'^Dialer\d',
    r'^Virtual-',
    r'^VirtualAccess\d',
    r'^VoIP',
]


def is_non_physical(port):
    if not port or port in ('unknown', ''):
        return False
    for p in NON_PHYSICAL_PATTERNS:
        if re.match(p, port, re.IGNORECASE):
            return True
    return False


def cleanup(dry_run=True):
    with app.app_context():
        all_conns = ConnectionPath.query.all()
        bad_conns = []

        for c in all_conns:
            bad_source = is_non_physical(c.source_port)
            bad_target = is_non_physical(c.target_port)
            if bad_source or bad_target:
                src_dev = Device.query.get(c.source_device_id)
                tgt_dev = Device.query.get(c.target_device_id)
                src_name = src_dev.name if src_dev else f"#{c.source_device_id}"
                tgt_name = tgt_dev.name if tgt_dev else f"#{c.target_device_id}"
                bad_conns.append({
                    'id': c.id,
                    'source': f"{src_name}:{c.source_port}",
                    'target': f"{tgt_name}:{c.target_port}",
                    'bad_side': 'source' if bad_source else 'target',
                    'bad_port': c.source_port if bad_source else c.target_port,
                    'protocol': c.discovered_by or c.discovery_protocol or 'unknown',
                    'obj': c,
                })

        if not bad_conns:
            print("✅ 没有发现使用非物理端口的连接记录。")
            return

        print(f"发现 {len(bad_conns)} 条使用非物理端口的连接：\n")
        for i, item in enumerate(bad_conns, 1):
            print(f"  #{i}  ID={item['id']}  [{item['protocol']}]")
            print(f"      {item['source']}  ↔  {item['target']}")
            marker = '^^^^' if item['bad_side'] == 'source' else '     '
            marker2 = '^^^^' if item['bad_side'] == 'target' else '     '
            print(f"      {marker}                     {marker2}")
            print(f"      非物理端口: {item['bad_port']}")
            print()

        if dry_run:
            print(f"[DRY RUN] 以上 {len(bad_conns)} 条记录将会被删除。加 --no-dry-run 实际执行。\n")
        else:
            for item in bad_conns:
                db.session.delete(item['obj'])
            db.session.commit()
            print(f"✅ 已删除 {len(bad_conns)} 条非物理端口连接记录。\n")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv and '--no-dry-run' not in sys.argv
    cleanup(dry_run=dry_run)
