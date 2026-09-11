# -*- coding: utf-8 -*-
"""连接数据治理：状态重算 / 端口冲突仲裁 / MAC 端口归一。默认 DRY-RUN。

用法：
    python scripts/ops/fix_link_integrity.py             # 预览
    python scripts/ops/fix_link_integrity.py --execute   # 落库
"""
import argparse
import sys

sys.path.insert(0, 'D:/asset')

from app import app  # noqa: F401  (注册蓝图与模型)
from utils.link_integrity import (refresh_link_status, resolve_port_conflicts,
                                  normalize_mac_ports, find_port_conflicts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()

    with app.app_context():
        print('=' * 74)
        print('1) 按接口实际状态重算链路状态')
        chg = refresh_link_status(execute=args.execute)
        if not chg:
            print('   无需变更')
        for c in chg:
            print(f"   #{c['id']:<5} {c['old']:<8} -> {c['new']:<8} {c['desc']}")

        print('=' * 74)
        print('2) 端口冲突仲裁（同一端口多个对端）')
        for dev_id, port, conns in find_port_conflicts():
            print(f"   设备#{dev_id} 端口 {port} 被 {len(conns)} 条连接占用: "
                  f"{[c.id for c in conns]}")
        plans = resolve_port_conflicts(execute=args.execute)
        for p in plans:
            print(f"   #{p['conn_id']:<5} 判为陈旧(保留 #{p['winner_id']}) "
                  f"设备#{p['device_id']} {p['port']} | {p['peers']}")

        print('=' * 74)
        print('3) MAC 端口名归一')
        macs = normalize_mac_ports(execute=args.execute)
        if not macs:
            print('   无需变更')
        for m in macs:
            print(f"   #{m['id']:<5} {m['field']:<13} {m['old']} -> unknown")

        print('=' * 74)
        print(f'合计：状态 {len(chg)} 条、冲突 {len(plans)} 条、MAC 端口 {len(macs)} 处')
        print('[DRY-RUN] 未写入' if not args.execute else '[EXECUTED] 已写入数据库')


if __name__ == '__main__':
    main()
