# -*- coding: utf-8 -*-
"""utils/model_type_map.py 规则表回归测试（离线，不连数据库）。

用例来源：现网常见型号 + 本次 bug 现场（H3C S7506E 型号已识别但类型 unknown）
+ 易误判项（Catalyst 3850 交换机 vs ISR 3825 路由器、APC UPS 误判 AP 等）。
"""
import sys

sys.path.insert(0, 'D:/asset')

from utils.model_type_map import infer_from_model, infer_from_name

# (model, brand, 期望类型, 期望是否无线控制器)
CASES = [
    # ---- 本次 bug 现场 ----
    ('S7506E', 'H3C', 'switch', False),
    # ---- H3C ----
    ('S5130-28S-SI', 'H3C', 'switch', False),
    ('S10500', 'H3C', 'switch', False),
    ('S6820-56HF', 'H3C', 'switch', False),
    ('MSR3620', 'H3C', 'router', False),
    ('SR6608', 'H3C', 'router', False),
    ('SecPath F100-C-G5', 'H3C', 'firewall', False),
    ('WX2540H', 'H3C', 'other', True),
    ('WX5560H', 'H3C', 'other', True),
    ('WA6320', 'H3C', 'ap', False),
    ('R4900 G3', 'H3C', 'server', False),
    # ---- Huawei ----
    ('CE6865-48S6CQ', 'Huawei', 'switch', False),
    ('CE12800', 'Huawei', 'switch', False),
    ('S5720-28X-SI', 'Huawei', 'switch', False),
    ('AR2240', 'Huawei', 'router', False),
    ('NE40E-M2K', 'Huawei', 'router', False),
    ('USG6525E', 'Huawei', 'firewall', False),
    ('USG6550', 'Huawei', 'firewall', False),
    ('F1000-S', 'Huawei', 'firewall', False),
    ('RH2288H V3', 'Huawei', 'server', False),
    ('AC6508', 'Huawei', 'other', True),
    ('AP6050DN', 'Huawei', 'ap', False),
    ('AirEngine 5760-10', 'Huawei', 'ap', False),
    ('OceanStor 5300 V5', 'Huawei', 'storage', False),
    # ---- Cisco ----
    ('C9300-24P', 'Cisco', 'switch', False),
    ('Catalyst 2960', 'Cisco', 'switch', False),
    ('C3850', 'Cisco', 'switch', False),          # 易误判为 ISR 38xx 路由器
    ('C3650', 'Cisco', 'switch', False),
    ('N5K-C5548UP', 'Cisco', 'switch', False),
    ('ISR4331', 'Cisco', 'router', False),
    ('ISR3825', 'Cisco', 'router', False),
    ('C2911', 'Cisco', 'router', False),
    ('ASA5525', 'Cisco', 'firewall', False),
    ('FTD-2110', 'Cisco', 'firewall', False),
    ('AIR-AP3802I', 'Cisco', 'ap', False),
    ('AIR-CT3504-K9', 'Cisco', 'other', True),
    ('C9800-40', 'Cisco', 'other', True),
    # ---- Ruijie ----
    ('RG-S5750-24GT4XS', 'Ruijie', 'switch', False),
    ('RG-NBS3100-24GT4SFP', 'Ruijie', 'switch', False),
    ('RG-RSR20-X', 'Ruijie', 'router', False),
    ('RG-WALL 1600', 'Ruijie', 'firewall', False),
    ('RG-AP820-I', 'Ruijie', 'ap', False),
    ('RG-WS7204-A', 'Ruijie', 'other', True),
    # ---- Fortinet / Juniper ----
    ('FortiGate 100E', 'Fortinet', 'firewall', False),
    ('FortiSwitch 124E', 'Fortinet', 'switch', False),
    ('FortiAP 221C', 'Fortinet', 'ap', False),
    ('EX4300-48T', 'Juniper', 'switch', False),
    ('QFX5100-48S', 'Juniper', 'switch', False),
    ('MX204', 'Juniper', 'router', False),
    ('SRX340', 'Juniper', 'firewall', False),
    # ---- 服务器 / 存储 ----
    ('PowerEdge R740', 'Dell', 'server', False),
    ('PowerVault ME4024', 'Dell', 'storage', False),
    ('DL380 Gen10', 'HPE', 'server', False),
    ('2930F', 'Aruba', 'switch', False),
    ('NF5280M6', 'Inspur', 'server', False),
    ('NetApp FAS2720', 'NetApp', 'storage', False),
    # ---- TP-Link / D-Link / MikroTik / Ubiquiti ----
    ('TL-SG3428', 'TP-Link', 'switch', False),
    ('DGS-3120-24TC', 'D-Link', 'switch', False),
    ('CRS328-24P', 'MikroTik', 'switch', False),
    ('RB3011UiAS', 'MikroTik', 'router', False),
    ('UAP-AC-PRO', 'Ubiquiti', 'ap', False),
    # ---- 不应命中（返回 None，保持 unknown 由上层兜底） ----
    ('APC Smart-UPS 1500', 'APC', None, False),
    ('', '', None, False),
    (None, None, None, False),
    ('H3C', 'H3C', None, False),
]

# 名称兜底用例（手工建设备、无型号）：(name, 期望类型)
NAME_CASES = [
    ('LBFL_4F_SW1', 'switch'),
    ('6HL-3F-NW-S3600-1', 'switch'),
    ('NeiWang_CunChu_03jigui', 'storage'),
    ('LBFL_4F_xinPOE', 'switch'),
    ('AC_WX2540-H', 'other'),
    ('核心交换机-A', 'switch'),
    ('Device-3868DDA0AAF1', None),
    ('AC', None),
    ('H3C', None),
]

failures = []
print('===== 型号 → 类型 =====')
for model, brand, want_type, want_ac in CASES:
    got = infer_from_model(model, brand)
    got_type = got['device_type'] if got else None
    got_ac = bool(got and got['is_wireless_controller'])
    ok = (got_type == want_type) and (got_ac == want_ac)
    flag = 'OK ' if ok else 'FAIL'
    if not ok:
        failures.append(f'model={model!r} brand={brand!r} 期望={want_type}/ac={want_ac} 实得={got_type}/ac={got_ac}')
    print(f'{flag} {str(model)[:22]:<22} {str(brand)[:9]:<9} -> {str(got_type):<8} ac={got_ac}')

print('===== 名称兜底 → 类型 =====')
for name, want in NAME_CASES:
    got = infer_from_name(name)
    got_type = got['device_type'] if got else None
    ok = got_type == want
    flag = 'OK ' if ok else 'FAIL'
    if not ok:
        failures.append(f'name={name!r} 期望={want} 实得={got_type}')
    print(f'{flag} {name[:26]:<26} -> {str(got_type)}')

if failures:
    print('\n=== 失败用例 ===')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print(f'\n===== ALL {len(CASES) + len(NAME_CASES)} CASES PASSED =====')
