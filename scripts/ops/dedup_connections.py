"""
一次性脚本：清理 connection_paths 表中已有的重复链路。
策略（按优先级）：
    1. 优先保留 discovered_by='lldp' 的连接
    2. 其次保留端口名更精确的（不是 'unknown' 或 'Port-N'）
    3. 再次保留更早创建的

重复判定：对每一对设备 (dev_a, dev_b)，任何方向上有多条链路都视为重复。

运行方式：
    python dedup_connections.py --dry-run   # 仅预览，不实际删除
    python dedup_connections.py             # 实际执行清理
"""
import os
import sys
import re

# 使脚本可从任意目录运行（scripts/ops -> 项目根）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from collections import defaultdict
from urllib.parse import urlparse

import pymysql
from dotenv import load_dotenv

load_dotenv()


def load_db_config():
    """从 .env / 环境变量读取 MySQL 连接配置。"""
    url = os.environ.get('DATABASE_URL', '').strip()
    if url.startswith('mysql'):
        parsed = urlparse(url)
        return {
            'host': parsed.hostname or 'localhost',
            'port': parsed.port or 3306,
            'user': parsed.username or 'root',
            'password': parsed.password or '',
            'database': (parsed.path or '/').lstrip('/') or 'asset',
            'charset': 'utf8mb4',
        }
    return {
        'host': os.environ.get('DB_HOST', 'localhost'),
        'port': int(os.environ.get('DB_PORT', '3306')),
        'user': os.environ.get('DB_USER', 'root'),
        'password': os.environ.get('DB_PASSWORD', ''),
        'database': os.environ.get('DB_NAME', 'asset'),
        'charset': 'utf8mb4',
    }


DRY_RUN = '--dry-run' in sys.argv

PORT_PLACEHOLDER = re.compile(r'^(Port-\d+|unknown|)$', re.IGNORECASE)


def port_quality(port_name):
    """端口名质量评分：越精确分越高。"""
    if not port_name:
        return 0
    if PORT_PLACEHOLDER.match(port_name):
        return 1
    return 10  # 像 GigabitEthernet0/0/1 这种


def rank_connection(row):
    """返回保留优先级分（越大越值得保留）。row 至少包含 8 列。"""
    disc = row[5] if len(row) > 5 else ''
    discovery_proto = row[6] if len(row) > 6 else ''
    sp = row[3] if len(row) > 3 else ''
    tp = row[4] if len(row) > 4 else ''
    created = row[7] if len(row) > 7 else None
    score = 0
    if (disc or '').lower() == 'lldp' or (discovery_proto or '').lower() == 'lldp':
        score += 1000
    score += port_quality(sp) + port_quality(tp)
    if created is not None:
        try:
            score -= int(created.timestamp()) / 1e9
        except Exception:
            pass
    return score


def main():
    cfg = load_db_config()
    print(f"[配置] 连接 {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}")
    conn = pymysql.connect(**cfg)
    cur = conn.cursor()

    cur.execute("""
        SELECT cp.id, cp.source_device_id, cp.target_device_id,
               cp.source_port, cp.target_port,
               cp.discovered_by, cp.discovery_protocol, cp.created_at,
               ds.name AS src_name, dt.name AS tgt_name
        FROM connection_paths cp
        LEFT JOIN devices ds ON ds.id = cp.source_device_id
        LEFT JOIN devices dt ON dt.id = cp.target_device_id
        ORDER BY cp.created_at ASC
    """)
    rows = cur.fetchall()

    pairs = defaultdict(list)
    for row in rows:
        cid, src, tgt = row[0], row[1], row[2]
        key = (min(src, tgt), max(src, tgt))
        pairs[key].append(row)

    duplicates = []
    for key, group in pairs.items():
        if len(group) <= 1:
            continue
        # 按 rank 排序，分高者保留
        group_sorted = sorted(group, key=rank_connection, reverse=True)
        keep = group_sorted[0]
        for dup in group_sorted[1:]:
            duplicates.append((dup, keep, key))

    if not duplicates:
        print("[OK] 没有发现重复链路，无需清理。")
        cur.close()
        conn.close()
        return

    print(f"\n发现 {len(duplicates)} 条重复链路：")
    print(f"{'ID':>6}  {'源设备':>12}  {'目标设备':>20}  {'源端口':>22}  {'目标端口':>22}  {'来源':>10}  →  保留")
    print("-" * 130)
    for dup, keep, key in duplicates:
        cid, src, tgt, sp, tp, disc, dproto, created, sn, tn = dup
        kid, ksrc, ktgt, ksp, ktp, kd, kdp, kcreated, ksn, ktn = keep
        arrow = "═"
        print(f"{cid:>6}  {sn or '?':>12}  {tn or '?':>20}  "
              f"{sp or '?':>22}  {tp or '?':>22}  {disc or '?':>10}  {arrow}>  "
              f"#{kid} ({ksn or '?'} ↔ {ktn or '?'}, {ksp} ↔ {ktp}, {kd})")

    if DRY_RUN:
        print(f"\n[Dry Run] 将删除 {len(duplicates)} 条记录（未实际执行）。去掉 --dry-run 参数后运行。")
    else:
        dup_ids = [d[0][0] for d in duplicates]
        placeholders = ','.join(['%s'] * len(dup_ids))
        cur.execute(f"DELETE FROM connection_paths WHERE id IN ({placeholders})", dup_ids)
        conn.commit()
        print(f"\n[OK] 已删除 {cur.rowcount} 条重复链路。")

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
