#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AC 发现 AP 未匹配交换机端口 —— 诊断脚本（dry-run，只读，不改库）

用法：
    python diag_ac_poe_match.py                 # 自动取第一个无线控制器
    python diag_ac_poe_match.py --controller 192.168.4.34
    python diag_ac_poe_match.py --controller "AC名称"

它会回答三个核心问题：
    1. POE 交换机在库里被标成了什么 device_type？（是否因非 'switch'/'router' 被排除）
    2. 实际进入扫描列表的交换机有哪些？它们的 MAC 表/ARP 是否真的读得到？
    3. 那些"疑似交换机但被排除"的设备（如 poe_switch / unknown 的交换机）有哪些？

依赖：在能连 DB + 可达交换机 SNMP 的 Python 环境运行（需 flask / 项目依赖）。
"""
import sys
import argparse
import os

# 使脚本可从任意目录运行（scripts/ops -> 项目根）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))


def main():
    parser = argparse.ArgumentParser(description='AC 发现 AP 匹配诊断')
    parser.add_argument('--controller', default=None,
                        help='AC 控制器 IP 或名称；省略则取第一个无线控制器')
    args = parser.parse_args()

    from app import app, db
    from models.models import Device
    from sqlalchemy import func

    with app.app_context():
        # ---- 定位控制器 ----
        ctrl = None
        if args.controller:
            ctrl = Device.query.filter(
                (Device.management_ip == args.controller) |
                (Device.ip_address == args.controller) |
                (func.lower(Device.name) == args.controller.lower())
            ).first()
            if ctrl and not ctrl.is_wireless_controller:
                print(f"[注意] {args.controller} 不是无线控制器(is_wireless_controller=False)，仍按指定设备分析")
        if ctrl is None:
            ctrl = Device.query.filter_by(is_wireless_controller=True).first()
        if ctrl is None:
            print("[错误] 未找到无线控制器，请通过 --controller 指定 AC 的 IP 或名称")
            return
        print(f"=== 控制器: {ctrl.name} (id={ctrl.id}, IP={ctrl.management_ip}, "
              f"community={ctrl.snmp_community!r}, vendor={ctrl.controller_vendor!r}) ===\n")

        # ---- 1. device_type 分布（看 POE 交换机被标成啥）----
        print("【1】全库 device_type 分布：")
        dist = db.session.query(Device.device_type, func.count(Device.id)).group_by(Device.device_type).all()
        for dtype, cnt in sorted(dist, key=lambda x: -x[1]):
            print(f"    {str(dtype):<20} {cnt}")
        print()

        # ---- 2. 实际进入扫描列表的交换机（复刻 ac_discovery 的筛选）----
        from utils.ac_discovery import _is_scan_candidate
        all_managed = Device.query.filter(
            Device.management_ip.isnot(None),
            Device.id != ctrl.id,
        ).all()
        exact_switches = [d for d in all_managed if _is_scan_candidate(d)]
        print(f"【2】进入扫描列表的交换机（device_type in ('switch','router')，"
              f"或名称/型号带 PoE 特征）共 {len(exact_switches)} 台")
        for sw in exact_switches:
            print(f"    id={sw.id:<5} {sw.name:<30} type={sw.device_type:<10} "
                  f"mgmt_ip={sw.management_ip:<16} snmp_comm={sw.snmp_community!r}")
        print()

        # ---- 3. "疑似交换机但被排除"的设备（模糊匹配 device_type）----
        like_patterns = ['%switch%', '%router%', '%poe%', '%poe%']
        excluded = Device.query.filter(
            Device.management_ip.isnot(None),
            Device.id != ctrl.id,
            func.lower(Device.device_type).like('%switch%') |
            func.lower(Device.device_type).like('%router%') |
            func.lower(Device.device_type).like('%poe%')
        ).all()
        excluded_ids = {sw.id for sw in exact_switches}
        suspicious = [d for d in excluded if d.id not in excluded_ids]
        print(f"【3】疑似交换机/路由/POE 但被 exact 筛选排除的设备：共 {len(suspicious)} 台")
        print("    （这些设备若确实接了 AP，就是 AP 无法匹配的根因）")
        for d in suspicious:
            print(f"    id={d.id:<5} {d.name:<30} type={d.device_type!r:<14} "
                  f"mgmt_ip={d.management_ip:<16} snmp_comm={d.snmp_community!r}")
        print()

        # ---- 4. 对进入列表的交换机实测 MAC 表可读性 ----
        print("【4】对扫描列表内交换机实测 SNMP 可读性（MAC 表 + ARP）：")
        try:
            from blueprints.topology import get_mac_table, discover_lldp_neighbors
            from utils.ac_discovery import _read_arp_table
        except Exception as e:
            print(f"    无法导入 SNMP 函数: {e}")
            return
        ctrl_comm = ctrl.snmp_community or 'public'
        for sw in exact_switches:
            sw_comm = sw.snmp_community or ctrl_comm
            mac_n = lldp_n = arp_n = 0
            err = ''
            try:
                mac_n = len(get_mac_table(sw.management_ip, sw_comm) or {})
            except Exception as e:
                err += f" MAC表失败:{e}"
            try:
                lldp_n = len(discover_lldp_neighbors(sw.management_ip, sw_comm) or [])
            except Exception as e:
                err += f" LLDP失败:{e}"
            try:
                arp_n = len(_read_arp_table(sw.management_ip, sw_comm, '2c') or {})
            except Exception as e:
                err += f" ARP失败:{e}"
            status = 'OK' if (mac_n or lldp_n or arp_n) else 'EMPTY/FAIL'
            print(f"    {sw.name:<28} comm={sw_comm:<12} MAC={mac_n:<6} "
                  f"LLDP={lldp_n:<5} ARP={arp_n:<6} -> {status}{err}")
        print()
        print("诊断完成。若【3】有大量设备，请把它们的 device_type 改为 'switch' 再重跑 AC 发现；")
        print("（device_type 标错但名称/型号带 PoE 特征的交换机，新版本 ac_discovery 已自动纳入扫描）")
        print("若【4】某交换机 EMPTY/FAIL，请检查其 snmp_community 与网络可达性。")


if __name__ == '__main__':
    main()
