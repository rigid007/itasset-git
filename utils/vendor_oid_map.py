# -*- coding: utf-8 -*-
"""sysObjectID → 厂商/型号识别表。

数据来源：IANA Private Enterprise Numbers（IANA-PEN-MIB）公开注册库
（https://www.iana.org/assignments/enterprise-numbers/），企业 OID 前缀为
公开注册信息，无授权问题。型号模式为各厂商 sysObjectID 树的常见形态。

用法：
    from utils.vendor_oid_map import identify_by_sys_object_id
    ident = identify_by_sys_object_id('1.3.6.1.4.1.25506.1.2017...')
    # → {'brand': 'H3C', 'device_type': 'switch', 'model': '', 'matched': '1.3.6.1.4.1.25506'}

设计要点：
  - 前缀按"最长匹配优先"（先精确子树，再退到企业根）；
  - curated 前缀未命中时，取根 PEN 查 IANA 全量注册表兜底
    （data/iana_pen.json.gz，66,648 条，scripts/build/gen_iana_pen_map.py 生成）；
  - 只给 device_type 提供提示（hint），最终分类仍由调用方结合
    sysDescr/sysName 关键词裁决；
  - 与 utils/snmp_utils.infer_device_type_from_snmp 协同：本表先定
    brand / device_type 底盘，原 sysDescr 关键词逻辑作为细化与兜底。
"""

# ------------------------------------------------------------------
# 企业 OID 前缀 → 厂商（IANA PEN 注册号 → 厂商名）
# 键为 sysObjectID 下的企业子树前缀（含 1.3.6.1.4.1 前缀），匹配时
# 按 key 长度降序做前缀匹配。
# ------------------------------------------------------------------
VENDOR_OID_PREFIXES = {
    # ---- 国产主流 ----
    '1.3.6.1.4.1.2011':   {'brand': 'Huawei',   'aliases': ['华为', 'HUAWEI']},
    '1.3.6.1.4.1.25506':  {'brand': 'H3C',      'aliases': ['新华三']},
    '1.3.6.1.4.1.25506.1': {'brand': 'H3C'},    # Comware 网络设备子树
    # 锐捷：4881 = Ruijie / 星网锐捷网络
    '1.3.6.1.4.1.4881':   {'brand': 'Ruijie',   'aliases': ['锐捷']},
    # 中兴
    '1.3.6.1.4.1.3902':   {'brand': 'ZTE',      'aliases': ['中兴']},
    # 迈普
    '1.3.6.1.4.1.3320':   {'brand': 'Maipu',    'aliases': ['迈普']},
    # DCN 神州数码网络（原 3320 之外，DCN 用 1991 系）
    '1.3.6.1.4.1.1991':   {'brand': 'DCN',      'aliases': ['神州数码网络']},
    # 网神/网康（奇安信）
    '1.3.6.1.4.1.34172':  {'brand': 'QiAnXin',  'aliases': ['奇安信']},
    # 深信服
    '1.3.6.1.4.1.35047':  {'brand': 'Sangfor',  'aliases': ['深信服']},
    # 海康威视（存储/网络）
    '1.3.6.1.4.1.39165':  {'brand': 'Hikvision', 'aliases': ['海康威视']},
    # 锐捷无线（RG-AC/AP 走同一企业树）

    # ---- 国际主流 ----
    '1.3.6.1.4.1.9':      {'brand': 'Cisco'},                     # ciscoProducts
    '1.3.6.1.4.1.9.1':    {'brand': 'Cisco'},                     # ciscoProducts 具体产品
    '1.3.6.1.4.1.2636':   {'brand': 'Juniper', 'aliases': ['瞻博网络']},
    '1.3.6.1.4.1.14823':  {'brand': 'Aruba',   'aliases': ['Aruba Networks']},
    '1.3.6.1.4.1.11':     {'brand': 'HP'},                         # Hewlett-Packard
    '1.3.6.1.4.1.674':    {'brand': 'Dell',   'aliases': ['Dell EMC']},
    '1.3.6.1.4.1.674.10892': {'brand': 'Dell', 'note': 'iDRAC BMC'},  # Dell OpenManage
    '1.3.6.1.4.1.24681':  {'brand': 'QNAP'},                       # NAS
    '1.3.6.1.4.1.789':    {'brand': 'NetApp'},                     # 存储
    '1.3.6.1.4.1.8072':   {'brand': 'net-snmp', 'note': 'Linux/net-snmp agent'},  # UCDavis net-snmp
    '1.3.6.1.4.1.2021':   {'brand': 'net-snmp', 'note': 'UCD-SNMP-MIB'},
    '1.3.6.1.4.1.311':    {'brand': 'Microsoft', 'note': 'Windows SNMP agent'},
    '1.3.6.1.4.1.77.1':   {'brand': 'Microsoft', 'note': 'Windows LAN Manager'},
    '1.3.6.1.4.1.8072.3.2': {'brand': 'net-snmp', 'note': 'Linux'},
    '1.3.6.1.4.1.6876':   {'brand': 'VMware',  'note': 'ESXi'},
    '1.3.6.1.4.1.2533':   {'brand': 'Buffalo'},
    '1.3.6.1.4.1.318':    {'brand': 'APC',    'note': 'UPS'},      # 施耐德/APC 电源
    '1.3.6.1.4.1.476':    {'brand': 'Eaton',  'note': 'UPS'},
    '1.3.6.1.4.1.13742':  {'brand': 'Raritan', 'note': 'PDU'},
    '1.3.6.1.4.1.2':      {'brand': 'IBM'},
    '1.3.6.1.4.1.232':    {'brand': 'HPE', 'note': 'ProLiant/iLO'},
    '1.3.6.1.4.1.19046':  {'brand': 'Lenovo'},
    '1.3.6.1.4.1.20301':  {'brand': 'F5',    'note': 'BIG-IP'},
    '1.3.6.1.4.1.3375':   {'brand': 'F5',    'note': 'BIG-IP'},
    '1.3.6.1.4.1.1588':   {'brand': 'Fortinet', 'aliases': ['飞塔']},
    '1.3.6.1.4.1.30803':  {'brand': 'SonicWall'},
    '1.3.6.1.4.1.3076':   {'brand': 'Palo Alto Networks'},
    '1.3.6.1.4.1.15586':  {'brand': 'Check Point'},
    '1.3.6.1.4.1.562':    {'brand': 'Ericsson'},
    '1.3.6.1.4.1.45.1':   {'brand': 'Nokia'},
    '1.3.6.1.4.1.12356':  {'brand': 'Fortinet', 'note': '旧树'},
    '1.3.6.1.4.1.6889':   {'brand': 'Alcatel-Lucent Enterprise', 'note': 'ALE/ OmniSwitch'},
    '1.3.6.1.4.1.637':    {'brand': 'Alcatel-Lucent'},
    '1.3.6.1.4.1.2272':   {'brand': 'Extreme Networks', 'note': 'Enterasys'},
    '1.3.6.1.4.1.1916':   {'brand': 'Extreme Networks'},
    '1.3.6.1.4.1.1991.1': {'brand': 'Extreme Networks', 'note': '原 ExtremeWare'},  # 注：1991 与 DCN 冲突，见下方 SPECIAL_NOTES
    '1.3.6.1.4.1.30065':  {'brand': 'Arista'},
    '1.3.6.1.4.1.4413':   {'brand': 'D-Link'},
    '1.3.6.1.4.1.171':    {'brand': 'D-Link', 'note': '旧树'},
    '1.3.6.1.4.1.28966':  {'brand': 'Nokia'},
    '1.3.6.1.4.1.2650':   {'brand': 'Ruckus', 'note': '无线'},
    '1.3.6.1.4.1.2509':   {'brand': 'Extreme', 'note': '原 LVL7'},
    '1.3.6.1.4.1.874':    {'brand': 'ADTRAN'},
    '1.3.6.1.4.1.10923':  {'brand': 'Ruijie', 'note': '原实达网络'},
    '1.3.6.1.4.1.40065':  {'brand': 'Sohoware'},
    '1.3.6.1.4.1.6318':   {'brand': 'Comware'},
}

# 1991 号段冲突说明：IANA 注册 1991 = Extreme Networks，但 DCN（神州数码）
# 部分老设备也使用 1991.1 之外的子树。sysObjectID 以 1991 开头时依赖
# sysDescr 关键词二次判别（见 identify_by_sys_object_id 的 descr 消歧）。

# ------------------------------------------------------------------
# 厂商企业子树下的设备类型提示（sysObjectID 特定子段 → device_type hint）
# 仅收录高置信度的常见形态，未知形态返回空 hint 交给 sysDescr 裁决。
# ------------------------------------------------------------------
DEVICE_TYPE_HINTS = {
    # Huawei 2011.2 网络产品：.2.62 = CloudEngine 数据中心交换（box），
    # .2.22 = S 系列盒式交换机，.2.81 = USG 防火墙 等——具体子号随版本
    # 变动频繁，这里只做粗粒度提示，型号交给 sysDescr 正则。
    'Huawei': {'prefix': '1.3.6.1.4.1.2011.2'},
    'H3C': {'prefix': '1.3.6.1.4.1.25506.1'},
    'Ruijie': {'prefix': '1.3.6.1.4.1.4881'},
    'Cisco': {'prefix': '1.3.6.1.4.1.9.1'},
    'Juniper': {'prefix': '1.3.6.1.4.1.2636.1'},
}

# sysDescr 消歧关键词：号段存在多厂商共用时按 sysDescr 判别（见 _CONFLICT_PREFIXES）
_BRAND_SYSDESCR_KEYWORDS = {
    'DCN': ['dcn', '神州数码', 'digital china'],
    'Extreme Networks': ['extreme networks', 'enterasys', 'xos'],
    'Ruijie': ['ruijie', '锐捷', 'rg-'],
}

# 冲突号段：IANA 注册方 ≠ 实际使用方，需要 sysDescr 消歧。
# 值为该号段的候选厂商列表（按 sysDescr 关键词依次判别，全部未命中则
# 回落到 IANA 注册方，即映射表中的 brand）。
_CONFLICT_PREFIXES = {
    '1.3.6.1.4.1.1991': ['DCN', 'Extreme Networks'],
}


# ------------------------------------------------------------------
# IANA PEN 全量兜底（data/iana_pen.json.gz，66,648 条企业号）
# 由 scripts/build/gen_iana_pen_map.py 从 IANA 官方注册表生成，
# curated 前缀表未命中时按根 PEN 查此表。IANA 注册数据可自由使用。
# ------------------------------------------------------------------
import gzip  # noqa: E402
import json  # noqa: E402
import os as _os  # noqa: E402
import re as _re  # noqa: E402

_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_IANA_FILE = _os.path.join(_PROJECT_ROOT, 'data', 'iana_pen.json.gz')
_iana_cache = None

# IANA 组织名（或其首个逗号/括号前主体）→ 规范厂商名（大小写不敏感）
_IANA_NAME_CANON = {
    'ciscosystems': 'Cisco', 'cisco systems': 'Cisco',
    'huawei technology co.,ltd': 'Huawei', 'huawei technologies': 'Huawei',
    'h3c': 'H3C', 'hangzhou h3c technologies': 'H3C',
    'ruijie networks': 'Ruijie', 'start network technology': 'Ruijie',
    'juniper networks': 'Juniper',
    'dell inc': 'Dell', 'hewlett-packard': 'HP', 'hewlett packard enterprise': 'HPE',
    'zte corporation': 'ZTE', 'aruba networks': 'Aruba', 'aruba': 'Aruba',
    'arista networks': 'Arista', 'd-link systems': 'D-Link',
    'extreme networks': 'Extreme Networks', 'enterasys networks': 'Extreme Networks',
    'ubiquiti networks': 'Ubiquiti', 'mikrotik': 'MikroTik',
    'netgear': 'Netgear', 'zyxel communications': 'Zyxel',
    'fortinet inc': 'Fortinet', 'palo alto networks': 'Palo Alto Networks',
    'check point software': 'Check Point',
    'f5 networks': 'F5', 'f5 inc': 'F5',
    'nokia': 'Nokia', 'nokia solutions and networks': 'Nokia',
    'alcatel-lucent enterprise': 'Alcatel-Lucent Enterprise',
    'international business machines': 'IBM',
    'lenovo group': 'Lenovo', 'lenovo': 'Lenovo',
    'sangfor technologies': 'Sangfor', 'qnap systems': 'QNAP',
    'netapp': 'NetApp', 'apc': 'APC', 'eaton corporation': 'Eaton',
    'vmware inc': 'VMware', 'microsoft corporation': 'Microsoft',
    'sun microsystems': 'Oracle', 'oracle corporation': 'Oracle',
    'hikvision digital technology': 'Hikvision',
    'digital china networks': 'DCN', 'maipu communication': 'Maipu',
}


def _load_iana_pen():
    """懒加载 IANA PEN→组织名映射（进程内缓存，加载失败降级为空表）。"""
    global _iana_cache
    if _iana_cache is None:
        try:
            with gzip.open(_IANA_FILE, 'rt', encoding='utf-8') as f:
                _iana_cache = json.load(f).get('pen', {}) or {}
        except Exception:
            _iana_cache = {}
    return _iana_cache


def _canonicalize_iana_org(org):
    """IANA 组织名 → 规范厂商名：先全名精确匹配，再取逗号/括号前主体匹配。"""
    if not org:
        return ''
    key = org.lower().strip()
    if key in _IANA_NAME_CANON:
        return _IANA_NAME_CANON[key]
    base = _re.split(r'[,(\[]', org)[0].strip().rstrip('.')
    k2 = base.lower()
    if k2 in _IANA_NAME_CANON:
        return _IANA_NAME_CANON[k2]
    return base or org


def extract_pen(sys_object_id: str) -> str:
    """从 sysObjectID 提取根企业号（1.3.6.1.4.1.<PEN>.… → <PEN>）。"""
    parts = normalize_oid(sys_object_id).split('.')
    if len(parts) >= 7 and parts[:6] == ['1', '3', '6', '1', '4', '1']:
        return parts[6]
    return ''


def normalize_oid(oid: str) -> str:
    """规范化 OID 字符串：去首尾点号/空白/引号，小写。"""
    s = (oid or '').strip().strip('.').strip('"').lower()
    return s


def _prefix_match(oid_norm: str, prefix: str) -> bool:
    """OID 分量级前缀匹配（防止 '11' 误命中 '11863' 这类字符串前缀碰撞）。"""
    op = oid_norm.split('.')
    pp = normalize_oid(prefix).split('.')
    return len(op) >= len(pp) and op[:len(pp)] == pp


def identify_by_sys_object_id(sys_object_id: str, sys_descr: str = '') -> dict:
    """根据 sysObjectID 识别厂商，返回识别结果字典。

    返回:
        {
          'brand':   厂商名（未识别返回 ''）,
          'matched': 命中的 OID 前缀（未识别返回 ''）,
          'note':    备注（如 'Linux/net-snmp agent'）,
        }
    匹配规则：最长前缀优先；1991 等冲突树用 sysDescr 关键词消歧。
    """
    oid = normalize_oid(sys_object_id)
    if not oid:
        return {'brand': '', 'matched': '', 'note': ''}
    descr = (sys_descr or '').lower()

    # 最长前缀优先：把前缀表按 key 长度降序排序
    candidates = sorted(VENDOR_OID_PREFIXES.items(),
                        key=lambda kv: len(kv[0]), reverse=True)
    for prefix, info in candidates:
        if _prefix_match(oid, prefix):
            brand = info['brand']
            note = info.get('note', '')
            # 冲突号段消歧（如 1991: IANA 注册 Extreme，但 DCN 老设备共用）
            for conflict_root, cand_brands in _CONFLICT_PREFIXES.items():
                if _prefix_match(oid, conflict_root):
                    for cand in cand_brands:
                        for kw in _BRAND_SYSDESCR_KEYWORDS.get(cand, []):
                            if kw in descr:
                                return {'brand': cand, 'matched': prefix, 'note': note}
                    # 无关键词命中 → 回落 IANA 注册方
            return {'brand': brand, 'matched': prefix, 'note': note}

    # IANA 全量兜底：curated 前缀未命中 → 取根 PEN 查 IANA 注册表（66k+ 条）
    pen = extract_pen(oid)
    if pen:
        org = _load_iana_pen().get(pen, '')
        brand = _canonicalize_iana_org(org)
        if brand:
            return {'brand': brand, 'matched': '1.3.6.1.4.1.' + pen,
                    'note': 'IANA PEN 兜底'}
    return {'brand': '', 'matched': '', 'note': ''}


def known_brands():
    """返回识别表支持的全部厂商名（供 UI 下拉/校验使用）。"""
    return sorted({v['brand'] for v in VENDOR_OID_PREFIXES.values()})


def is_infra_agent(brand: str) -> bool:
    """判断该 brand 是否是主机/代理类（Linux/Windows/ESXi）而非网络设备。

    这类设备 sysObjectID 指向 SNMP agent 而非硬件平台，device_type
    应按服务器处理，brand 不应覆盖已有值。
    """
    return (brand or '') in {'net-snmp', 'Microsoft', 'VMware', 'Comware'}
