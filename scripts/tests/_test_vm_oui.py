# -*- coding: utf-8 -*-
"""宿主机识别工具单元测试（utils.vm_oui）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.vm_oui import (
    classify_lldp_capabilities,
    classify_port_macs,
    detect_hypervisor_platform,
    is_vm_mac,
    normalize_mac,
    pick_physical_nic_mac,
)


def test_normalize_mac():
    assert normalize_mac('00:50:56:AB:CD:EF') == '005056abcdef'
    assert normalize_mac('08-00-27-01-02-03') == '080027010203'
    assert normalize_mac('') == ''
    assert normalize_mac(None) == ''


def test_is_vm_mac():
    cases = {
        '00:50:56:aa:bb:cc': 'vmware',
        '00:0c:29:11:22:33': 'vmware',
        '00:15:5d:01:02:03': 'hyperv',
        '00:16:3e:11:22:33': 'xen',
        '52:54:00:11:22:33': 'kvm',
        '08:00:27:11:22:33': 'virtualbox',
        '00:1c:42:11:22:33': 'parallels',
        '54:e1:ad:43:20:29': ('', False),
    }
    for mac, expected in cases.items():
        is_vm, platform = is_vm_mac(mac)
        if isinstance(expected, tuple):
            assert is_vm is expected[1]
            assert platform == expected[0]
        else:
            assert is_vm is True
            assert platform == expected


def test_classify_port_macs():
    # 单 MAC -> leaf
    r = classify_port_macs(['54:e1:ad:43:20:29'])
    assert r['class'] == 'leaf'
    assert r['vm_count'] == 0

    # 多个非虚拟化 MAC -> 真级联/上行口
    r = classify_port_macs(['54:e1:ad:43:20:29', '3c:2c:30:aa:bb:cc'])
    assert r['class'] == 'switch_cascade'

    # 物理网卡 MAC + 多个 VM MAC -> 宿主机上行口
    r = classify_port_macs([
        '54:e1:ad:43:20:29',          # 物理网卡
        '00:50:56:aa:bb:01',          # VMware
        '00:50:56:aa:bb:02',          # VMware
        '00:0c:29:aa:bb:03',          # VMware
    ])
    assert r['class'] == 'hypervisor'
    assert r['vm_count'] == 3
    assert '54:e1:ad:43:20:29' in r['physical_macs']
    assert r['platform'] == 'vmware'

    # 全部为 VM MAC -> 仍判宿主机，但无物理网卡 MAC
    r = classify_port_macs(['00:50:56:aa:bb:01', '00:50:56:aa:bb:02'])
    assert r['class'] == 'hypervisor'
    assert r['physical_macs'] == []


def test_pick_physical_nic_mac():
    macs = ['00:50:56:aa:bb:01', '54:e1:ad:43:20:29']
    assert pick_physical_nic_mac(macs) == '54:e1:ad:43:20:29'
    # ARP 命中优先
    assert pick_physical_nic_mac(macs, {'54e1ad432029': '10.0.0.1'}) == '54:e1:ad:43:20:29'
    # 只有 VM MAC 时退化为任意一个
    assert pick_physical_nic_mac(['00:50:56:aa:bb:01']) == '00:50:56:aa:bb:01'
    assert pick_physical_nic_mac([]) == ''


def test_classify_lldp_capabilities():
    assert classify_lldp_capabilities(4) == 'switch'       # macBridge
    assert classify_lldp_capabilities(132) == 'switch'     # bridge + station
    assert classify_lldp_capabilities(16) == 'router'
    assert classify_lldp_capabilities(128) == 'host'       # station
    assert classify_lldp_capabilities('128') == 'host'
    assert classify_lldp_capabilities(0) == 'unknown'
    assert classify_lldp_capabilities(None) == 'unknown'


def test_detect_hypervisor_platform():
    assert detect_hypervisor_platform('VMware ESXi 7.0 U3') == 'vmware'
    assert detect_hypervisor_platform('Proxmox VE 8.2') == 'proxmox'
    assert detect_hypervisor_platform('QEMU/KVM Virtual Machine') == 'kvm'
    assert detect_hypervisor_platform('Windows Server 2022 Hyper-V') == 'hyperv'
    assert detect_hypervisor_platform('H3C Comware Software') == ''
    assert detect_hypervisor_platform(None) == ''


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"[OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
