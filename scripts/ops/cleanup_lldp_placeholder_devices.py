"""清理 LLDP 自动发现产生的 unknown 占位设备。

筛选条件（占位设备的典型特征）：
    device_type = 'unknown'
    AND status = 'unknown'
    AND management_ip IS NULL
    AND ip_address IS NULL
    AND mac_address IS NULL

这类设备是 LLDP 邻居仅有 sysName、既无 IP 也无 MAC、且库中无同名设备时，
由 run_protocol_discovery 自动创建的"死端"占位设备（现在已改为跳过不再创建）。
它们没有任何可达信息，只会污染 CMDB，并拖着一堆 dangling 连接。

用法：
    python cleanup_lldp_placeholder_devices.py            # 仅 dry-run，列出候选
    python cleanup_lldp_placeholder_devices.py --execute  # 真正删除
"""
import sys
import argparse
import os

# 使脚本可从任意目录运行（scripts/ops -> 项目根）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app import app
from models.models import Device, Interface, ConnectionPath
from extensions import db


def find_candidates():
    """返回符合占位设备特征的设备列表。"""
    return Device.query.filter(
        Device.device_type == 'unknown',
        Device.status == 'unknown',
        Device.management_ip.is_(None),
        Device.ip_address.is_(None),
        Device.mac_address.is_(None),
    ).all()


def related_connections(dev_id):
    return ConnectionPath.query.filter(
        db.or_(
            ConnectionPath.source_device_id == dev_id,
            ConnectionPath.target_device_id == dev_id,
        )
    ).all()


def related_interfaces(dev_id):
    return Interface.query.filter_by(device_id=dev_id).all()


def main():
    parser = argparse.ArgumentParser(description='清理 LLDP 自动发现的 unknown 占位设备')
    parser.add_argument('--execute', action='store_true',
                        help='真正执行删除（默认仅 dry-run 列出候选）')
    args = parser.parse_args()

    with app.app_context():
        candidates = find_candidates()
        total_conn = 0
        total_iface = 0
        print(f"候选占位设备共 {len(candidates)} 个")
        print("-" * 70)
        for d in candidates:
            conns = related_connections(d.id)
            ifaces = related_interfaces(d.id)
            total_conn += len(conns)
            total_iface += len(ifaces)
            # 仅展示名称前若干字符，便于人工核对
            sample = d.name[:40] if d.name else '(无名称)'
            print(f"  id={d.id:>6}  name={sample!r:<42} 连接={len(conns):>3} 接口={len(ifaces):>2}")
        print("-" * 70)
        print(f"合计：设备 {len(candidates)} 个，关联连接 {total_conn} 条，关联接口 {total_iface} 个")

        if not args.execute:
            print("\n[DRY-RUN] 未执行删除。确认无误后加 --execute 参数执行。")
            return

        # 执行删除：先删连接 → 接口 → 设备，避免外键约束报错
        deleted_conn = 0
        deleted_iface = 0
        deleted_dev = 0
        for d in candidates:
            for c in related_connections(d.id):
                db.session.delete(c)
                deleted_conn += 1
            for i in related_interfaces(d.id):
                db.session.delete(i)
                deleted_iface += 1
        # 批量删设备
        for d in candidates:
            db.session.delete(d)
            deleted_dev += 1
        db.session.commit()
        print(f"\n[EXECUTED] 已删除 设备 {deleted_dev} 个、连接 {deleted_conn} 条、接口 {deleted_iface} 个。")


if __name__ == '__main__':
    main()
