# utils/model_type_map.py
"""型号/名称 → 设备类型 推断表（P0-4）。

背景：
    P0-2/P0-3 之后品牌与型号（model）已能稳定采集，但 device_type 仍常落为 unknown。
    根因是旧逻辑仅靠 sysDescr 关键字（switch/router/交换机…）判类型，而大量设备
    （如 H3C S7506E 的 sysDescr = "H3C Comware Platform Software..."）根本不含类型词，
    而其型号本身强类型化：S7xxx=核心交换机、MSR=路由器、USG=防火墙、WA/WX=AP/AC。

设计原则：
    1. 只在"未知类型"时兜底，绝不覆盖已有判定（避免误伤人工修正过的设备）。
    2. 顺序：AP → AC(无线控制器) → 防火墙 → 存储 → 路由器 → 服务器 → 交换机（最宽泛放最后）。
    3. 锚定型号串起首（^），避免 "AR" 之类双字母词误命中（如 Storage/Camera）。
    4. 类型取值严格限定项目既有口径：switch/router/firewall/server/storage/ap/other
       （见 utils/utils.py get_device_color）。无线控制器无独立类型，返回 other 并置
       is_wireless_controller 标记（对应 models.Device.is_wireless_controller）。
"""
import re

# 允许输出的规范类型（与 get_device_color 口径一致）
VALID_TYPES = ('switch', 'router', 'firewall', 'server', 'storage', 'ap', 'other')

# (正则, 类型, 提示) —— 首个命中生效，顺序即优先级
MODEL_RULES = (
    # ---------- 无线 AP ----------
    (r'^(wa)\d{3,4}[a-z0-9\-]*$', 'ap', ''),                    # H3C WA6320 / WA4320
    (r'^ap[-\s]?\d{3,4}[a-z0-9\-]*$', 'ap', ''),                # Huawei AP6050DN / Aruba AP-515 / AP515
    (r'^air[-\s]?(ap|cap)[-\s]?\d{4}', 'ap', ''),               # Cisco AIR-AP3802I / AIR-CAP
    (r'^(uap|eap|tl[-\s]?ap|rg[-\s]?ap|fortiap)[-\s]?\d{0,4}', 'ap', ''),
    (r'^air?engine\s?\d{3,4}', 'ap', ''),                       # Huawei AirEngine 5760
    (r'^(iw|cap|ap)\d{3}[a-z0-9\-]*$', 'ap', ''),
    # ---------- 无线控制器 AC ----------
    (r'^(wx)\d{3,4}[a-z0-9\-]*$', 'other', 'ac'),               # H3C WX2540H / WX5560H
    (r'^ac\d{4}[a-z0-9\-]*$', 'other', 'ac'),                   # Huawei AC6508 / AC6005
    (r'^rg[-\s]?ws\d{0,4}', 'other', 'ac'),                     # 锐捷无线控制器
    (r'^(wlc|air[-\s]?ct\d{4})([-\s]?[a-z0-9]+)*$', 'other', 'ac'),  # Cisco WLC / AIR-CT3504-K9
    (r'^c?9800[-\s]?\d{0,2}[a-z0-9\-]*$', 'other', 'ac'),            # Cisco C9800-40
    # ---------- 防火墙 / 安全网关 ----------
    (r'^(usg)\d{3,4}[a-z0-9\-]*$', 'firewall', ''),             # Huawei USG6525E / USG6550
    (r'^f\d{3,4}[a-z0-9\-]*$', 'firewall', ''),                 # Huawei F100 / F1000-S
    (r'^(secpath[-\s]?)?f\d{2,4}[a-z0-9\-]*$', 'firewall', ''),   # H3C SecPath F100-C-G5
    (r'^(asa)\d{3,4}', 'firewall', ''),                         # Cisco ASA5525
    (r'^(ftd|firepower)', 'firewall', ''),
    (r'^(fortigate|fgt)[-\s]?\d{0,4}', 'firewall', ''),
    (r'^srx\d{3,4}', 'firewall', ''),                           # Juniper SRX
    (r'^rg[-\s]?wall', 'firewall', ''),                         # 锐捷 RG-WALL
    (r'^(af|ngfw|fw)[-\s]?\d{3,4}', 'firewall', ''),            # 深信服 AF / NGFW
    (r'^(pan|pa)-\d{3,4}', 'firewall', ''),                     # Palo Alto PA-3220
    # ---------- 存储 ----------
    (r'^(oceanstor|dorado|fusionsphere)', 'storage', ''),       # 华为 OceanStor
    (r'^(unity|powervault|vmax|vnx|netapp|freenas|storwize|fas\d{4})', 'storage', ''),
    (r'^(me4|msa)\d{3}', 'storage', ''),
    (r'存储|storage\s?array', 'storage', ''),
    # ---------- 路由器 ----------
    (r'^(msr)\d{2,4}[a-z0-9\-]*$', 'router', ''),               # H3C MSR3620
    (r'^sr66\d{0,2}[a-z0-9\-]*$', 'router', ''),
    (r'^ar\d{3,4}[a-z0-9\-]*$', 'router', ''),                  # Huawei AR2240 / AR6120
    (r'^(ne|netengine)\d{2,4}[a-z0-9\-]*$', 'router', ''),      # Huawei NE40E
    (r'^(isr|asr|csr)\d{0,4}[a-z0-9\-]*$', 'router', ''),       # Cisco ISR/ASR/CSR
    # Cisco ISR 数字系列：19xx/26xx/28xx/29xx/38(25|45)/39xx/43xx/44xx
    # 注意 3850/3650 是 Catalyst 交换机，不能落进 38/36 前缀，故 38 只收 3825/3845
    (r'^c?(19\d{2}|26\d{2}|28\d{2}|29\d{2}|38(25|45)|39\d{2}|43\d{2}|44\d{2})([-\s]\w+)?$',
     'router', ''),
    (r'^mx\d{2,4}[a-z0-9\-]*$', 'router', ''),                  # Juniper MX
    (r'^rg[-\s]?rsr', 'router', ''),                            # 锐捷 RSR
    (r'^(ccr|rb|hap|hex|ltap)\d{2,4}[a-z0-9\-]*$', 'router', ''),   # MikroTik
    (r'^(edgerouter|er[-\s]?\d{1,2})', 'router', ''),           # Ubiquiti
    (r'^router\s?\w*|路由器', 'router', ''),
    # ---------- 服务器 ----------
    (r'(poweredge|proliant|thinksystem|uniserver|system\s?x)', 'server', ''),
    (r'^(rh|rh\d)\d{2,4}[a-z0-9\-]*$', 'server', ''),           # Huawei RH2288H / RH5885
    (r'^(dl|ml)\d{3}[a-z0-9\-]*$', 'server', ''),               # HPE DL380 / ML350
    (r'^nf\d{3,4}[a-z0-9\-]*$', 'server', ''),                  # 浪潮 NF5280M6
    (r'^(sr|r)\d{3,4}[a-z0-9\-]*$', 'server', ''),              # H3C R4900 / Dell R740 / SR650
    (r'^(2288|5288|5885|taishan)', 'server', ''),
    (r'^(x\d{4}|ucs)', 'server', ''),                           # IBM x3650 / Cisco UCS
    # ---------- 交换机（最宽泛，放最后） ----------
    (r'^(s)\d{3,5}[a-z0-9\-]*$', 'switch', ''),                 # H3C S7506E / S5130-28S / S10500
    (r'^(ce|cloudengine)\s?\d{3,4}[a-z0-9\-]*$', 'switch', ''), # Huawei CE6865 / CloudEngine
    (r'^(ex|qfx)\d{3,4}[a-z0-9\-]*$', 'switch', ''),            # Juniper EX/QFX
    (r'^(catalyst|c)\s?\d{3,4}[a-z0-9\-\s]*$', 'switch', ''),   # Cisco Catalyst 2960 / C9300-24P
    (r'^(nexus|n)\d{1,2}k?[-\s]?\d{0,4}[a-z0-9\-]*$', 'switch', ''),  # Nexus / N9K
    (r'^rg[-\s]?(s\d{3,4}|nbs|cs\d{3})', 'switch', ''),         # 锐捷 RG-S5750 / RG-NBS
    (r'^(tl[-\s]?s[fg]|t1[6-9]00g|jetstream)', 'switch', ''),   # TP-Link TL-SG / T1600G
    (r'^(dgs|des|dxs|d[\-]?link)[-\s]?\d{0,4}', 'switch', ''),  # D-Link
    (r'^(usw|crs|css|fortiswitch|flex|sn)[-\s]?\d{0,4}', 'switch', ''),
    (r'交换机|^switch\s?\d{0,4}$', 'switch', ''),
)

# 品牌相关的纯数字型号（HPE/Aruba 常用 4 位数字交换机型号）
_NUMERIC_BRAND_RULES = (
    (('hpe', 'aruba', 'hp'), r'^\d{4}[a-z0-9\-]*$', 'switch'),  # 2930F / 6300M / 2540
    (('aruba',), r'^(70|72|90)\d{2}(-\w+)?$', 'other'),         # Aruba 7005/7205 控制器
)

# 名称兜底规则（手工建的设备没型号，仅有名字；保守匹配）
NAME_RULES = (
    (r'(路由器|router)', 'router', ''),
    (r'(防火墙|firewall|\bfw\b|网关)', 'firewall', ''),
    (r'(存储|cunchu|storage|磁盘阵列|nas\b|san\b)', 'storage', ''),
    (r'(服务器|server|宿主机)', 'server', ''),
    (r'(wx\d{3,4}|ac\d{4}|wlc|控制器)', 'other', 'ac'),
    (r'(\bwa\d{3,4}|\bap[-\s]?\d{3,4}|\bap\b(?!c)|瘦ap|无线)', 'ap', ''),
    # 中英文 + 拼音（现网命名常混用拼音：HuiJu=汇聚、JieRu=接入、HeXin=核心）
    (r'(交换机|switch|\bsw\b|[_/\-]sw\d|\bs\d{4}\b|poe'
     r'|汇聚|接入|核心|huiju|jieru|hexin|jiaohuan)', 'switch', ''),
)

_COMPILED = tuple((re.compile(p, re.IGNORECASE), t, h) for p, t, h in MODEL_RULES)
_NAME_COMPILED = tuple((re.compile(p, re.IGNORECASE), t, h) for p, t, h in NAME_RULES)


def _result(device_type, hint):
    return {
        'device_type': device_type if device_type in VALID_TYPES else 'other',
        'is_wireless_controller': hint == 'ac',
    }


def infer_from_model(model, brand=''):
    """按型号反推设备类型。命中返回 {'device_type', 'is_wireless_controller'}，否则 None。"""
    m = (model or '').strip()
    if not m:
        return None
    b = (brand or '').strip().lower()
    # 型号里含版本尾缀（如 "RH2288H V3"）时取首段
    head = m.split()[0] if m.split() else m
    for pat, dtype, hint in _COMPILED:
        if pat.search(head) or pat.search(m):
            return _result(dtype, hint)
    for brands, pat, dtype in _NUMERIC_BRAND_RULES:
        if b in brands and re.match(pat, head, re.IGNORECASE):
            return _result(dtype, 'ac' if dtype == 'other' else '')
    return None


def infer_from_name(name):
    """按设备名称兜底推断（仅用于无任何型号信息的手工设备），保守匹配。"""
    n = (name or '').strip()
    if not n or len(n) < 3:
        return None
    for pat, dtype, hint in _NAME_COMPILED:
        if pat.search(n):
            return _result(dtype, hint)
    return None


def infer_device_type(model='', brand='', name=''):
    """型号优先、名称兜底。均不命中返回 None。"""
    return infer_from_model(model, brand) or infer_from_name(name)
