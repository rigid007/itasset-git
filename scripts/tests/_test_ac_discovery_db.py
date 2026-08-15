#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AC 发现优化 —— 真实数据库回归（SNMP 打桩，全部回滚不落库）。

前置条件：
    1. 本地 MySQL80 已启动，asset 库可连（.env 中 DATABASE_URL / DB_*）；
    2. 运行前建议确认库里已有 AC 发现产生的 AP（本脚本按 device_type='ap' 取 3 台真实 AP）。

脚本做什么：
    - 用真实 AC（GAM-AC）与真实 AP/交换机数据，模拟 H3C 状态表 + 名称表 + 交换机 MAC/LLDP；
    - 跑完整 _discover_aps_core，验证：
        a) AP 名称由序列号纠正为 AC 内配置名（_enrich_ap_names + _upsert_ap_device 覆盖规则）；
        b) 级联口过滤 + PoE 择优：AP 只连到 PoE 交换机，不连非 PoE 楼层交换机；
        c) 旧的错误 edge_ap 连接被 _replace_stale_ap_links 清理；
    - 最后 db.session.rollback()，数据库保持原样。

运行：python _test_ac_discovery_db.py
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '.env')))
except Exception:
    pass

from flask import Flask
from extensions import db, init_extensions
from models.models import Device, ConnectionPath
from utils import ac_discovery as ad


def build_app() -> Flask:
    app = Flask(__name__)
    host = os.environ.get('DB_HOST', 'localhost')
    port = os.environ.get('DB_PORT', '3306')
    user = os.environ.get('DB_USER', 'root')
    pwd = os.environ.get('DB_PASSWORD', '')
    name = os.environ.get('DB_NAME', 'asset')
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f'mysql+pymysql://{user}:{pwd}@{host}:{port}/{name}?charset=utf8mb4')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'ac-discovery-db-regression-test'
    init_extensions(app)
    return app


def octet_index(text: str) -> str:
    """构造 OCTET STRING 型 OID 索引后缀（首字节=长度，后续为 ASCII 码）。"""
    return str(len(text)) + '.' + '.'.join(str(ord(c)) for c in text)


def main():
    app = build_app()
    import blueprints.topology as topo  # 用于打桩 discover_lldp_neighbors / get_mac_table

    with app.app_context():
        # ---------- 1. 真实控制器与交换机 ----------
        controller = Device.query.filter_by(is_wireless_controller=True).first()
        assert controller, '库中无无线控制器'
        print(f'控制器: {controller.name} ({controller.management_ip}, vendor={controller.controller_vendor})')

        poe_sw = Device.query.filter_by(management_ip='10.1.1.1').first()
        non_poe_sw = Device.query.filter_by(management_ip='10.1.0.1').first()
        assert poe_sw and non_poe_sw, '缺少 PoE 或非 PoE 测试交换机'
        print(f'PoE 交换机: {poe_sw.name} (id={poe_sw.id}, model={poe_sw.model})')
        print(f'非 PoE 交换机: {non_poe_sw.name} (id={non_poe_sw.id}, model={non_poe_sw.model})')

        # ---------- 2. 取 3 台真实 AP（现名应为序列号）----------
        aps = Device.query.filter_by(device_type='ap').limit(3).all()
        assert len(aps) == 3 and all(a.management_ip for a in aps)
        ap_serials = [a.name for a in aps]          # 旧代码把序列号写进了 name
        ap_ips = [a.management_ip for a in aps]
        ap_macs = ['02:aa:bb:cc:dd:01', '02:aa:bb:cc:dd:02', '02:aa:bb:cc:dd:03']
        ap_names = ['AP-3F-01', 'AP-3F-02', 'AP-3F-03']
        print('回归 AP:')
        for a, s, ip, m, n in zip(aps, ap_serials, ap_ips, ap_macs, ap_names):
            print(f'  {s} | {ip} | 新名称={n} | 新MAC={m}')

        # ---------- 3. 模拟 H3C 状态表 + 名称表 ----------
        status_rows = {}
        name_map = {}
        for serial, ip, mac, name in zip(ap_serials, ap_ips, ap_macs, ap_names):
            idx = octet_index(serial)
            status_rows[idx] = {'1': serial, '2': ip, '3': mac, '4': '5'}  # 5=run 在线
            name_map[idx] = name

        ad._walk_table = lambda *a, **k: status_rows
        ad._walk_to_index_map = lambda *a, **k: name_map
        ad._read_arp_table = lambda *a, **k: {}
        import utils.snmp_utils as su
        su.snmp_get = lambda *a, **k: 'GAM-AC'

        # ---------- 4. 模拟交换机 MAC 表 / LLDP ----------
        # PoE 交换机：端口1/2 各直连 1 台 AP（叶口）；端口24 为上行（多 MAC）
        poe_mac_table = {
            ap_macs[0]: '1',
            ap_macs[1]: '2',
            ap_macs[2]: '3',            # 第 3 台 AP 也在 PoE 交换机（端口3）
            '02:00:00:00:00:10': '24',  # 上行口上的其它设备
            '02:00:00:00:00:11': '24',
            '02:00:00:00:00:12': '24',
            '02:00:00:00:00:13': '24',
        }
        # 非 PoE 楼层交换机：级联口24 同时学到 3 台 AP + 大量 PC（应被过滤）
        non_poe_mac_table = {
            ap_macs[0]: '24',
            ap_macs[1]: '24',
            ap_macs[2]: '24',
            '02:00:00:00:00:20': '24',
            '02:00:00:00:00:21': '24',
            '02:00:00:00:00:22': '24',
            '02:00:00:00:00:23': '24',
            '02:00:00:00:00:24': '1',   # 一个直连 PC
        }
        lldp_poe = [
            {'remote_chassis': ap_macs[0], 'local_interface_name': 'GigabitEthernet1/0/1',
             'remote_sysname': ap_names[0]},
            {'remote_chassis': ap_macs[1], 'local_interface_name': 'GigabitEthernet1/0/2',
             'remote_sysname': ap_names[1]},
        ]
        lldp_non_poe = [
            {'remote_chassis': '02:aa:bb:cc:00:99', 'local_interface_name': 'GigabitEthernet1/0/24',
             'remote_sysname': poe_sw.name},
        ]

        def fake_get_mac_table(ip, community='public'):
            if ip == poe_sw.management_ip:
                return dict(poe_mac_table)
            if ip == non_poe_sw.management_ip:
                return dict(non_poe_mac_table)
            return {}

        def fake_lldp(ip, community='public'):
            if ip == poe_sw.management_ip:
                return [dict(n) for n in lldp_poe]
            if ip == non_poe_sw.management_ip:
                return [dict(n) for n in lldp_non_poe]
            return []

        topo.get_mac_table = fake_get_mac_table
        topo.discover_lldp_neighbors = fake_lldp
        ad._resolve_dot1d_to_ifname = lambda ip, dot1d, comm, ver: f'GigabitEthernet1/0/{dot1d}'

        # ---------- 5. 预先插入一条“错误”旧连接（AP1 -> 非 PoE 交换机级联口）----------
        stale_conn = ConnectionPath(
            source_device_id=non_poe_sw.id,          # 小 ID 为 source（与 _upsert_ap_connection 归一化一致）
            source_port='GigabitEthernet1/0/24',
            target_device_id=aps[0].id,
            target_port='unknown',
            connection_type='physical',
            link_status='active',
            discovered_by='AC',
            discovery_protocol='CAPWAP',
            auto_discovered=True,
            neighbor_managed=True,
            link_role='edge_ap',
            confidence=100,
        )
        db.session.add(stale_conn)
        db.session.flush()
        stale_id = stale_conn.id
        print(f'预置错误旧连接: {non_poe_sw.name}:GigabitEthernet1/0/24 -> AP{aps[0].id} (id={stale_id})')

        # ---------- 6. 跑完整发现（commit 打桩为 no-op，最后整体回滚）----------
        progress = {'phase': '', 'current': 0, 'total': 0, 'percent': 0, 'log': []}
        real_commit = db.session.commit
        db.session.commit = lambda: None
        try:
            result = ad._discover_aps_core(controller, community='gamyy', version='2c',
                                           progress=progress)
            # ---- 断言必须在 rollback 前做（rollback 会使对象过期回读旧值）----
            print()
            print('=== 发现结果 ===')
            for k in ('total', 'created', 'updated', 'linked', 'stale_removed', 'errors'):
                print(f'  {k}: {result[k]}')
            print()
            for line in result['details']:
                print('  detail:', line)

            assert result['total'] == 3, result
            assert result['created'] == 0 and result['updated'] == 3, result
            assert result['linked'] == 3, result
            assert result['stale_removed'] == 1, result
            assert result['errors'] == 0, result

            # a) 名称纠正 + MAC/序列号补全
            for idx, dev in enumerate(aps):
                assert dev.name == ap_names[idx], f'{dev.name} != {ap_names[idx]}'
                assert dev.mac_address == ap_macs[idx], dev.mac_address
                assert dev.serial_number == ap_serials[idx], dev.serial_number
            print()
            print('[OK] 3 台 AP 名称由序列号纠正为 AC 内配置名，MAC/序列号已补全')

            # b) 连接只指向 PoE 交换机，且旧错误连接被清理
            poe_links = ConnectionPath.query.filter(
                ConnectionPath.link_role == 'edge_ap',
                db.or_(
                    ConnectionPath.source_device_id == poe_sw.id,
                    ConnectionPath.target_device_id == poe_sw.id,
                ),
            ).all()
            non_poe_links = ConnectionPath.query.filter(
                ConnectionPath.link_role == 'edge_ap',
                db.or_(
                    ConnectionPath.source_device_id == non_poe_sw.id,
                    ConnectionPath.target_device_id == non_poe_sw.id,
                ),
            ).all()
            stale_gone = db.session.get(ConnectionPath, stale_id) is None
            assert len(poe_links) == 3, poe_links
            assert len(non_poe_links) == 0, non_poe_links
            assert stale_gone, '预置的错误旧连接未被清理'
            print('[OK] 3 条连接全部落在 PoE 交换机；非 PoE 交换机 0 条连接；错误旧连接已被清理')
        finally:
            db.session.rollback()
            db.session.commit = real_commit

        # c) 回滚生效：库中不应有任何新增连接残留
        after_count = ConnectionPath.query.filter_by(link_role='edge_ap').count()
        print(f'[OK] 回滚后库中 edge_ap 连接数 = {after_count}（期望 0，未落库）')
        assert after_count == 0

        print()
        print('真实数据库回归：全部通过（数据已回滚，未改动库）')


if __name__ == '__main__':
    main()
