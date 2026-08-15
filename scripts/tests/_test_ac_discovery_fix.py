#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AC 发现优化（AP 名称/序列号 + 非 PoE 交换机过滤）的轻量单测。

纯逻辑测试，不连 DB、不发 SNMP；SNMP/DB 依赖全部打桩。
运行：python _test_ac_discovery_fix.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from utils import ac_discovery as ad


def sw(id_, name, dtype='switch', model='', brand='', manufacturer='', mgmt='1.1.1.1'):
    return types.SimpleNamespace(
        id=id_, name=name, device_type=dtype, model=model, brand=brand,
        manufacturer=manufacturer, management_ip=mgmt, snmp_community=None,
    )


def test_parse_h3c_status_row():
    t = ad.VENDOR_TABLES['h3c'][0]
    assert t['mac'] == '3' and t['ip'] == '2' and t['status'] == '4' and t['online'] == {'5'}
    # 状态表：索引=序列号(OCTET STRING 带长度前缀)，列1=序列号，列2=IP，列3=MAC，列4=状态(5=run)
    index = '21.50.48.50.51.53.65.49.71.78.67.49.54.51.48.48.48.48.56.51'  # 210235A1GNC163000083
    cols = {'3': 'aa:bb:cc:dd:ee:ff', '2': '192.168.4.20',
            '1': '210235A1GNC163000083', '4': '5'}
    mac, name, ap_ip, serial, status = ad._parse_ap_row(t, index, cols)
    assert mac == 'aa:bb:cc:dd:ee:ff'
    assert name == '', f'状态表不应把序列号索引当名称，实际 {name!r}'
    assert ap_ip == '192.168.4.20'
    assert serial == '210235A1GNC163000083'
    assert status == 'online'
    # 状态 4=config 应判离线
    _, _, _, _, status2 = ad._parse_ap_row(t, index, dict(cols, **{'4': '4'}))
    assert status2 == 'offline'
    print('[OK] _parse_ap_row H3C 状态表：名称不再取序列号索引')


def test_parse_tunnel_name_index():
    # name_from_index 表（如旧隧道表）仍从索引解码名称
    t = {'base': 'x', 'name_from_index': True, 'ip': '2'}
    mac, name, ap_ip, serial, status = ad._parse_ap_row(
        t, '3.65.80.45.51.70.45.48.49', {'2': '10.0.0.2'})
    assert name == 'AP-3F-01', name
    assert mac == '' and serial == '' and status == 'online'
    print('[OK] _parse_ap_row 名称索引表：正常解码名称')


def test_looks_like_serial():
    assert ad._looks_like_serial('210235A1GNC163000083') is True
    assert ad._looks_like_serial('219801A0HQC171000013') is True
    assert ad._looks_like_serial('AP-3F-01') is False
    assert ad._looks_like_serial('OfficeAP12') is False      # 不足 12 位
    assert ad._looks_like_serial('aaaaaaaaaaaa') is False     # 纯字母，非混合
    assert ad._looks_like_serial('123456789012') is False     # 纯数字，非混合
    assert ad._looks_like_serial('') is False
    print('[OK] _looks_like_serial')


def test_is_poe_switch():
    assert ad._is_poe_switch(sw(1, 'S5130S-28P-PWR-EI')) is True
    assert ad._is_poe_switch(sw(2, '接入交换机', dtype='poe_switch')) is True
    assert ad._is_poe_switch(sw(3, 'PoE 接入', model='S5720-28X-PWR-LI')) is True
    assert ad._is_poe_switch(sw(4, 'core-switch-01')) is False
    assert ad._is_poe_switch(None) is False
    print('[OK] _is_poe_switch')


def test_is_scan_candidate():
    # 正式标记的交换机/路由器必扫
    assert ad._is_scan_candidate(sw(1, 'S5130S', dtype='switch')) is True
    assert ad._is_scan_candidate(sw(2, '核心路由', dtype='router')) is True
    # device_type 被误标为 unknown/poe_switch、但名称/型号带 PoE 特征的接入交换机也要扫
    # （实测案例 XMZ-2F-S5048poe type=unknown，AP MAC 学在其 GE1/0/16 上）
    assert ad._is_scan_candidate(sw(3, 'XMZ-2F-S5048poe', dtype='unknown')) is True
    # 真实型号 S5048PV5-EI-PWR（名称/型号任一含 PWR/PoE 即命中）
    assert ad._is_scan_candidate(sw(8, 'XMZ-2F-S5048poe', dtype='unknown',
                                    model='S5048PV5-EI-PWR')) is True
    assert ad._is_scan_candidate(sw(4, 'S5048', dtype='poe_switch')) is True
    # 普通 unknown 设备 / AP / 无管理 IP 的不扫
    assert ad._is_scan_candidate(sw(5, '某服务器', dtype='unknown')) is False
    assert ad._is_scan_candidate(sw(6, '5L-2f-207', dtype='ap')) is False
    assert ad._is_scan_candidate(sw(7, 'S5048poe', mgmt=None)) is False
    print('[OK] _is_scan_candidate：unknown 但带 PoE 特征的交换机纳入扫描')


def test_candidate_ranking():
    poe = sw(1, 'PoE接入', model='-PWR-')
    core = sw(2, 'core', model='S6800')
    c_lldp = {'sw': core, 'port': 'G1/0/1', 'is_dot1d': False, 'source': 'lldp',
              'port_macs': 0, 'poe': False}
    c_poe = {'sw': poe, 'port': 'G1/0/2', 'is_dot1d': True, 'source': 'mac',
             'port_macs': 1, 'poe': True}
    c_core = {'sw': core, 'port': 'G1/0/3', 'is_dot1d': True, 'source': 'mac',
              'port_macs': 2, 'poe': False}
    # LLDP 直连 > PoE 叶口 > 非 PoE 多 MAC 口
    assert ad._best_candidate([c_core, c_poe, c_lldp]) is c_lldp
    assert ad._best_candidate([c_core, c_poe]) is c_poe
    assert ad._best_candidate([c_core]) is c_core
    assert ad._best_candidate([]) is None
    # PoE 加分：同为 1 MAC 时 PoE 胜出
    c_non_poe_leaf = {'sw': core, 'port': 'G1/0/4', 'is_dot1d': True, 'source': 'mac',
                      'port_macs': 1, 'poe': False}
    assert ad._best_candidate([c_non_poe_leaf, c_poe]) is c_poe
    print('[OK] _best_candidate/_candidate_score：LLDP/叶口/PoE 优先级')


def test_enrich_ap_names():
    aps = {
        'k1': {'mac': 'aa:bb:cc:dd:ee:ff', 'name': '', 'ip': '', 'serial': '210235A1GNC163000083',
               'status': 'online', '_index': '21.50.48.50.51.53.65.49.71.78.67.49.54.51.48.48.48.48.56.51'},
        'k2': {'mac': '11:22:33:44:55:66', 'name': '', 'ip': '', 'serial': '',
               'status': 'online', '_index': '18.54.56.49.55.52.48.56.53.51.49.51.50.48.50.48.51.49.49'},
        'k3': {'mac': '11:22:33:44:55:77', 'name': 'AlreadyName', 'ip': '', 'serial': '',
               'status': 'online', '_index': ''},
    }
    name_map = {
        '21.50.48.50.51.53.65.49.71.78.67.49.54.51.48.48.48.48.56.51': 'AP-3F-01',
        '18.54.56.49.55.52.48.56.53.51.49.51.50.48.50.48.51.49.49': 'AP-2F-02',
    }
    ad._walk_to_index_map = lambda *a, **k: name_map
    got = ad._enrich_ap_names(aps, 'h3c', '10.0.0.1', 'public', '2c', progress=None)
    assert got == 2, got
    assert aps['k1']['name'] == 'AP-3F-01'
    assert aps['k2']['name'] == 'AP-2F-02'      # 走 _index 兜底
    assert aps['k3']['name'] == 'AlreadyName'   # 已有名称不覆盖
    # 非 H3C 不处理
    got2 = ad._enrich_ap_names(aps, 'huawei', '10.0.0.1', 'public', '2c', progress=None)
    assert got2 == 0
    print('[OK] _enrich_ap_names：按序列号补全 AC 内 AP 名称')


def test_build_switch_index_cascade_filter():
    import blueprints.topology as topo
    mac_table = {
        'aa:bb:cc:dd:ee:01': '1',   # 端口1：1 个 MAC（AP 直连口）
        'aa:bb:cc:dd:ee:02': '2',   # 端口2：5 个 MAC（级联口）
        'aa:bb:cc:dd:ee:03': '2',
        'aa:bb:cc:dd:ee:04': '2',
        'aa:bb:cc:dd:ee:05': '2',
        'aa:bb:cc:dd:ee:06': '2',
        'ff:ff:ff:ff:ff:01': '1',   # 组播，应被过滤
        '01:00:5e:00:00:01': '1',   # 组播，应被过滤
    }
    topo.get_mac_table = lambda ip, comm: mac_table
    topo.discover_lldp_neighbors = lambda ip, comm: []
    ad._read_arp_table = lambda *a, **k: {}
    switches = [sw(10, 'POE-SW-01', model='-PWR-', mgmt='10.0.0.10')]
    index = ad._build_switch_index(switches, 'public', '2c', progress=None)
    assert 'aa:bb:cc:dd:ee:01' in index['mac']
    cands = index['mac']['aa:bb:cc:dd:ee:01']
    assert len(cands) == 1 and cands[0]['port'] == '1' and cands[0]['port_macs'] == 1
    assert 'aa:bb:cc:dd:ee:02' not in index['mac'], '级联口上的 MAC 不应进入索引'
    assert 'aa:bb:cc:dd:ee:03' not in index['mac']
    assert 'ff:ff:ff:ff:ff:01' not in index['mac']
    print('[OK] _build_switch_index：级联口（MAC>=3）与组播 MAC 被过滤')


def test_match_prefers_poe():
    poe = sw(20, 'POE-SW', model='-PWR-')
    core = sw(21, 'CORE-SW', model='S6800')
    index = {
        'mac': {
            'aa:bb:cc:dd:ee:ff': [
                {'sw': core, 'port': '101', 'is_dot1d': True, 'source': 'mac',
                 'port_macs': 2, 'poe': False},
                {'sw': poe, 'port': 'G1/0/1', 'is_dot1d': True, 'source': 'mac',
                 'port_macs': 1, 'poe': True},
            ],
        },
        'name': {},
        'ip_mac': {},
    }
    ad._resolve_dot1d_to_ifname = lambda *a, **k: None
    dev, port = ad._match_ap_in_index('aa:bb:cc:dd:ee:ff', 'AP-X', index, 'public', '2c')
    assert dev is poe and port == 'G1/0/1', (dev, port)
    print('[OK] _match_ap_in_index：多候选时择优 PoE 叶口')


def main():
    tests = [
        test_parse_h3c_status_row,
        test_parse_tunnel_name_index,
        test_looks_like_serial,
        test_is_poe_switch,
        test_is_scan_candidate,
        test_candidate_ranking,
        test_enrich_ap_names,
        test_build_switch_index_cascade_filter,
        test_match_prefers_poe,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception:
            import traceback
            print(f'[FAIL] {t.__name__}')
            traceback.print_exc()
            failed += 1
    print(f'\n结果：{len(tests) - failed}/{len(tests)} 通过')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
