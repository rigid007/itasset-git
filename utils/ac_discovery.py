"""无线控制器(AC) / CAPWAP AP 发现工具。

通过 SNMP 从无线控制器拉取下属 AP 清单（名称、IP、MAC、序列号、在线状态），
并把 AP 与接入(PoE)交换机端口匹配，形成 ConnectionPath 拓扑连接。

支持厂商（MIB 可能因固件版本不同而不同，已内置多套候选表）：
    cisco  (AIRESPACE-WIRELESS-MIB / CISCO-LWAPP-AP-MIB)
    h3c    (HH3C-WLAN-MIB hh3cWlanAPTable  +  新 Comware hwDot11ApTable)
    huawei (HUAWEI-WLAN-AP-MIB hwWlanApTable)
    aruba  (WLSX / aruba MIB)
    ruijie (RG-WLAN)

AP 与 PoE 交换机端口的匹配优先级：
    1. 遍历交换机 LLDP 邻居，用 AP 的 MAC/名称反查所在端口；
    2. 退化为遍历交换机 MAC 地址表，用 AP 的 MAC 反查学习端口（dot1d -> ifName）；
       级联/上行口（端口上 MAC 数过多）不参与匹配，PoE 交换机与叶端口优先，
       避免把 AP 错误匹配到上游非 PoE 交换机的级联口。

H3C 的 hh3cDot11APObjectStatusTable 索引是 AP 序列号且没有名称列，AP 名称需从
hh3cDot11APObjectTable 的 hh3cDot11CurrAPName(.8) 补全，不能把序列号索引当成名称。

为避免“逐 AP 扫描全部交换机”带来的 O(AP×交换机) 海量 SNMP 请求（曾导致 nginx 504），
本模块在匹配阶段**先一次性构建交换机端口索引**，再对每个 AP 做 O(1) 反查。

发现过程支持异步执行（start_ac_discovery）并实时上报进度/调试日志，
前端轮询 discover_aps_status 接口即可展示进度条与日志，避免 HTTP 请求超时。
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

from flask import current_app
from extensions import db
from models.models import Device, Interface, ConnectionPath

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 异步任务状态存储（单进程内有效；多 worker 部署需改为 Redis/DB 共享）
# ---------------------------------------------------------------------------
AC_DISCOVERY_JOBS: Dict[str, Dict] = {}


def _p_log(progress, msg: str, level: str = 'info'):
    """向任务进度日志追加一行（progress 为任务字典，None 时只写 logger）。"""
    if progress is None:
        getattr(logger, level, logger.info)(msg)
        return
    progress['log'].append({'t': time.strftime('%H:%M:%S'), 'msg': msg, 'level': level})
    if len(progress['log']) > 800:
        progress['log'].pop(0)
    getattr(logger, level, logger.info)(msg)


def _p_phase(progress, name: str, current: int = 0, total: int = 0, percent: Optional[int] = None):
    """更新任务阶段名称与进度计数。percent 可显式指定总体进度（用于跨阶段单调递增）。"""
    if progress is None:
        return
    progress['phase'] = name
    progress['current'] = current
    progress['total'] = total
    progress['percent'] = percent if percent is not None else (int(current * 100 / total) if total else 0)


# ---------------------------------------------------------------------------
# 厂商 MIB 表（OID 为列 OID；表索引通常为 AP 的 MAC 地址，故可从 OID 后缀解析出 MAC）
# 每个厂商可配置多套候选表，按顺序尝试，第一套命中即用。
# 字段说明：
#   base   : 表条目(Entry) OID，snmpwalk 它即可拿到该表所有列
#   name/ip/mac/serial/status : 各列在 base 之后的“列号”
#   online : 表示 AP 在线(normal/associated/run)的 status 取值集合
# ---------------------------------------------------------------------------
VENDOR_TABLES: Dict[str, List[Dict[str, object]]] = {
    'h3c': [
        {   # hh3cDot11APObjectStatusTable（CAPWAP 运行状态表，本固件实测存在）：
            # 索引为 AP 序列号(OCTET STRING)，列1=AP 序列号，列2=AP IP，列3=AP MAC，
            # 列4=运行状态（1=join,2=joinConfirm,3=download,4=config,5=run 在线）。
            # 注意：本表没有 AP 名称列，索引也不是名称，绝不能把索引解码成名称
            # （曾导致 AP 名称显示为序列号）；名称由 _enrich_ap_names 从
            # hh3cDot11APObjectTable 的 hh3cDot11CurrAPName(.8) 按序列号补全。
            'base': '1.3.6.1.4.1.25506.2.75.2.1.1.1',
            'ip': '2', 'mac': '3', 'serial': '1', 'serial_from_index': True,
            'status': '4', 'online': {'5'},
        },
        {   # 老 Comware（HH3C-WLAN-MIB hh3cWlanAPTable，部分固件存在）：MAC=列1，名称=列2，IP=列3，状态=列4，序列号=列5
            'base': '1.3.6.1.4.1.25506.2.75.1.1.1.1',
            'name': '2', 'ip': '3', 'mac': '1', 'serial': '5', 'status': '4',
            'online': {'1'},  # 1=run, 2=config, 3=down
        },
        {   # 新 Comware V7 / WX（hwDot11ApTable，华为分支 2011）
            'base': '1.3.6.1.4.1.2011.10.1.1.1.1',
            'name': '2', 'ip': '6', 'mac': '3', 'serial': '5', 'status': '7',
            'online': {'1'},
        },
    ],
    'huawei': [
        {   # HUAWEI-WLAN-AP-MIB hwWlanApTable（索引为 AP MAC）
            'base': '1.3.6.1.4.1.2011.6.139.13.3.3.1',
            'name': '4', 'ip': '13', 'mac': '1', 'serial': '2', 'status': '6',
            'online': {'8'},  # 8=normal
        },
    ],
    'cisco': [
        {   # AIRESPACE-WIRELESS-MIB（索引为 AP MAC）
            'base': '1.3.6.1.4.1.14179.2.2.1.1',
            'name': '3', 'ip': '19', 'mac': '1', 'serial': '16', 'status': '6',
            'online': {'1'},  # 1=associated
        },
    ],
    'aruba': [
        {   # WLSX-WLAN-MIB wlanAPEntry
            'base': '1.3.6.1.4.1.14823.2.2.1.1.3.1',
            'name': '2', 'ip': '4', 'mac': '3', 'serial': '17', 'status': '8',
            'online': {'1', 'up'},
        },
    ],
    'ruijie': [
        {   # RG-WLAN rgWlanAPTable
            'base': '1.3.6.1.4.1.4881.1.1.10.18.1.1',
            'name': '2', 'ip': '3', 'mac': '1', 'serial': '16', 'status': '6',
            'online': {'1'},  # 1=run
        },
    ],
}

# sysObjectID 厂商前缀 -> vendor 键
SYS_OBJECT_PREFIX = {
    '1.3.6.1.4.1.14179': 'cisco',
    '1.3.6.1.4.1.25506': 'h3c',
    '1.3.6.1.4.1.2011': 'h3c',   # H3C 新 MIB 走 2011 分支
    '1.3.6.1.4.1.14823': 'aruba',
    '1.3.6.1.4.1.4881': 'ruijie',
}

# ---------------------------------------------------------------------------
# MIB 诊断：walk 一组候选 OID，定位真实 AP 表（不同固件 OID 差异很大）
# 每项：(展示名, OID)
# ---------------------------------------------------------------------------
PROBE_OIDS: List[Tuple[str, str]] = [
    ('hh3cDot11APObjectStatusTable (25506.2.75.2.1.1.1)', '1.3.6.1.4.1.25506.2.75.2.1.1.1'),
    ('hh3cDot11CurrAPName 名称列 (25506.2.75.2.1.2.1.8)', '1.3.6.1.4.1.25506.2.75.2.1.2.1.8'),
    ('hh3cWlanAPTable (25506.2.75.1.1.1.1)', '1.3.6.1.4.1.25506.2.75.1.1.1.1'),
    ('hh3cWlanAp 组/含AP表 (25506.2.75.1.1)', '1.3.6.1.4.1.25506.2.75.1.1'),
    ('hwDot11ApTable (2011.10.1.1.1.1)', '1.3.6.1.4.1.2011.10.1.1.1.1'),
    ('hwDot11 组 (2011.10.1.1)', '1.3.6.1.4.1.2011.10.1.1'),
]


def probe_ac_mib(controller: Device, community: Optional[str] = None,
                 version: Optional[str] = None,
                 oids: Optional[List[Tuple[str, str]]] = None) -> Dict:
    """诊断：walk 一组候选 OID，返回每个 OID 的命中行数与样本，帮助定位真实 AP 表 OID。

    返回 {'ip','community','version','reachable','sys_name','probes':[{label,oid,count,sample,error}], 'error'}
    """
    from utils.snmp_utils import snmp_get, snmp_walk
    ip = controller.management_ip or controller.ip_address
    out: Dict = {'ip': ip, 'community': community, 'version': version,
                 'reachable': False, 'sys_name': None, 'probes': []}
    if not ip:
        out['error'] = '控制器无管理 IP'
        return out
    community = community or controller.snmp_community or 'public'
    version = version or ('2c' if (controller.snmp_version or 2) == 2 else '1')
    out['community'] = community
    out['version'] = version
    sys_name = snmp_get(ip, community, version, '1.3.6.1.2.1.1.5.0', timeout=5)
    out['reachable'] = sys_name is not None
    out['sys_name'] = sys_name
    if sys_name is None:
        out['error'] = 'SNMP 不可达，请确认 community/版本/网络'
        return out
    for label, oid in (oids or PROBE_OIDS):
        try:
            rows = snmp_walk(ip, oid, community, version=version, timeout=10, retries=1)
            sample = [{'oid': o, 'value': v} for o, v in rows[:8]]
            out['probes'].append({
                'label': label, 'oid': oid,
                'count': len(rows), 'sample': sample, 'error': None,
            })
        except Exception as e:  # pragma: no cover - snmp_walk 内部已吞异常
            out['probes'].append({
                'label': label, 'oid': oid, 'count': 0, 'sample': [], 'error': str(e),
            })
    return out


def normalize_mac(mac: str) -> str:
    if not mac:
        return ''
    mac = mac.strip().lower()
    # 去掉可能的厂商/OID 前缀中的非十六进制字符
    hex_parts = re.findall(r'[0-9a-f]{2}', mac.replace(':', '').replace('-', '').replace('.', ''))
    if len(hex_parts) >= 6:
        return ':'.join(hex_parts[-6:])
    return ''


def _mac_from_oid_suffix(suffix: str) -> str:
    """从 OID 后缀（最后 6 段十进制）解析 MAC 地址。"""
    parts = [p for p in suffix.strip('.').split('.') if p != '']
    try:
        nums = [int(p) for p in parts[-6:]]
    except ValueError:
        return ''
    if len(nums) != 6:
        return ''
    return ':'.join(f'{n:02x}' for n in nums)


def _decode_octet_index(suffix: str) -> str:
    """从 OID 索引（ASCII OCTET STRING 编码，如 AP 名称）解码为可读字符串。

    H3C 隧道表索引形如 .20.50.49.48...（首字节常为长度前缀，其余为名称的 ASCII 码）。
    首字节是长度前缀时跳过；并过滤不可打印字节，得到干净的 AP 名称。
    """
    nums = []
    for p in suffix.strip('.').split('.'):
        p = p.strip()
        if p == '':
            continue
        try:
            nums.append(int(p))
        except ValueError:
            return ''
    if not nums:
        return ''
    # 标准 OCTET STRING 索引：首字节为长度前缀（等于后续字节数）
    if len(nums) > 1 and nums[0] == len(nums) - 1:
        nums = nums[1:]
    # 仅保留可打印 ASCII，过滤长度前缀等不可打印字节
    out = ''.join(chr(b) for b in nums if 32 <= b <= 126)
    return out.strip()


_SERIAL_LIKE_RE = re.compile(r'^[0-9A-Za-z]{12,}$')


def _looks_like_serial(text: str) -> bool:
    """判断字符串是否形如设备序列号（12 位以上纯字母数字、且字母数字混合）。

    用于纠正历史数据：早期版本把 H3C 状态表的序列号索引当成 AP 名称入库，
    这些“名称”需要在下一次发现时被 AC 内配置的名称覆盖。
    """
    s = (text or '').strip()
    if not _SERIAL_LIKE_RE.match(s):
        return False
    return any(c.isdigit() for c in s) and any(c.isalpha() for c in s)


def _detect_vendor(controller: Device, community: str = 'public', version: str = '2c') -> str:
    """确定控制器厂商：优先用 device.controller_vendor，否则按 sysObjectID 自动识别。"""
    if controller.controller_vendor and controller.controller_vendor != 'auto':
        return controller.controller_vendor
    from utils.snmp_utils import snmp_get
    ip = controller.management_ip or controller.ip_address
    if not ip:
        return 'auto'
    oid = snmp_get(ip, community, version, '1.3.6.1.2.1.1.2.0', timeout=5)
    if not oid:
        return 'auto'
    oid = str(oid).strip()
    for prefix, vendor in SYS_OBJECT_PREFIX.items():
        if oid.startswith(prefix):
            return vendor
    return 'auto'


def _walk_table(ip: str, base: str, community: str, version: str,
                timeout: int = 10, retries: int = 1,
                total_timeout: Optional[int] = None,
                on_line=None, raise_on_error: bool = False) -> Dict[str, Dict[str, str]]:
    """snmpwalk 一张表(Entry OID)，返回 {索引后缀: {列号: 值}}。

    这样只需一次 walk 就能拿到该表全部列，比逐列 walk 更省时，也避免因单个列号
    写错而整体失败——只要 name/mac 列命中即可。

    total_timeout/on_line/raise_on_error 透传给 snmp_walk：H3C 等厂家的 WLAN 表
    单条处理极慢，整表 walk 可能需数分钟，调用方应传入较大的 total_timeout 并
    用 on_line 做实时进度，避免被提前掐断且用户无感知。
    """
    from utils.snmp_utils import snmp_walk
    out: Dict[str, Dict[str, str]] = {}
    entries = snmp_walk(ip, base, community, version=version, timeout=timeout, retries=retries,
                        total_timeout=total_timeout, on_line=on_line, raise_on_error=raise_on_error)
    base_norm = base.rstrip('.').lstrip('.')
    for oid_str, value in entries:
        o = oid_str.lstrip('.')
        if not o.startswith(base_norm):
            continue
        rest = o[len(base_norm):].lstrip('.')
        parts = rest.split('.')
        if len(parts) < 2:
            continue
        col = parts[0]
        index = '.'.join(parts[1:])
        out.setdefault(index, {})[col] = str(value).strip()
    return out


def _parse_ap_row(t: Dict, index: str, cols: Dict[str, str]) -> Tuple[str, str, str, str, str]:
    """解析 MIB 表的一行，返回 (mac, name, ap_ip, serial, status)。

    名称规则：仅当表显式声明“索引即名称”(name_from_index) 时才从索引解码；
    否则取名称列，绝不无条件把索引解码成名称——H3C 状态表的索引是序列号，
    曾因此把 AP 名称写成序列号。
    """
    # MAC：优先取列，其次尝试从“MAC 型索引”解析
    mac_col = t.get('mac')
    mac_raw = cols.get(str(mac_col), '') if mac_col is not None else ''
    mac = normalize_mac(mac_raw)
    # name_from_index 表的索引是“名称(ASCII)”，回退会把名称末 6 字节错当 MAC，必须跳过
    if not mac and not t.get('name_from_index'):
        mac = _mac_from_oid_suffix(index)
    # 名称：列取名称或索引解码（仅当声明索引即名称）
    if t.get('name_from_index'):
        name = _decode_octet_index(index)
    elif t.get('name') is not None:
        name = cols.get(str(t['name']), '')
    else:
        name = ''
    ap_ip = cols.get(str(t['ip']), '') if t.get('ip') is not None else ''
    serial = cols.get(str(t['serial']), '') if t.get('serial') is not None else ''
    if not serial and t.get('serial_from_index'):
        serial = _decode_octet_index(index)
    # 状态：无状态列时默认在线
    if t.get('status') is None:
        status = 'online'
    else:
        status_raw = cols.get(str(t['status']), '')
        status = 'online' if str(status_raw).strip() in set(t.get('online', {'1'})) else 'offline'
    return mac, name, ap_ip, serial, status


def _walk_to_index_map(ip: str, oid: str, community: str, version: str,
                       timeout: int = 15, retries: int = 2) -> Dict[str, str]:
    """snmpwalk 一列，返回 {OID后缀(索引): 值}。供 MAC 表反查端口时使用。"""
    from utils.snmp_utils import snmp_walk
    out: Dict[str, str] = {}
    entries = snmp_walk(ip, oid, community, version=version, timeout=timeout, retries=retries)
    base_norm = oid.rstrip('.').lstrip('.')
    for oid_str, value in entries:
        o = oid_str.lstrip('.')
        if not o.startswith(base_norm):
            continue
        suffix = o[len(base_norm):].lstrip('.')
        if suffix:
            out[suffix] = str(value).strip()
    return out


def _resolve_dot1d_to_ifname(ip: str, dot1d_port: str, community: str, version: str) -> Optional[str]:
    """把 dot1d 端口号解析为 ifName（dot1dBasePortIfIndex -> ifName）。"""
    try:
        base_map = _walk_to_index_map(ip, '1.3.6.1.2.1.17.1.4.1.2', community, version,
                                      timeout=8, retries=1)
        if_index = base_map.get(str(dot1d_port).lstrip('.'))
        if if_index:
            ifaces = _walk_ifnames(ip, community, version)
            for oid_str, val in ifaces:
                if oid_str.rstrip().endswith(f'.{if_index}'):
                    return str(val).strip()
    except Exception as e:
        logger.warning(f"解析 dot1d {dot1d_port} -> ifName 失败 ({ip}): {e}")
    return None


# ---------------------------------------------------------------------------
# ARP 表读取 —— 用 AC 自身的 ARP 表把 AP IP -> MAC 补全
# ---------------------------------------------------------------------------

# ipNetToMediaPhysAddress (OID 索引 = ifIndex.IP 各段)
_ARP_OID = '1.3.6.1.2.1.4.22.1.2'

# hh3cDot11CurrAPName：AC 内配置的 AP 名称列（索引为 AP 序列号 OCTET STRING）
_H3C_AP_NAME_OID = '1.3.6.1.4.1.25506.2.75.2.1.2.1.8'


def _read_arp_table(ip: str, community: str, version: str,
                    timeout: int = 8, retries: int = 1) -> Dict[str, str]:
    """读取设备 ARP 表，返回 {ip_address: normalized_mac}。

    OID 1.3.6.1.2.1.4.22.1.2 的索引为 ifIndex.a.b.c.d，值是 MAC（Hex-STRING）。
    _decode_hex_value 已修复：6 字节 hex 直接返回 xx:xx:xx:xx:xx:xx 格式，
    normalize_mac 再做一次标准化确保格式统一。
    """
    from utils.snmp_utils import snmp_walk
    arp: Dict[str, str] = {}
    try:
        entries = snmp_walk(ip, _ARP_OID, community, version=version,
                            timeout=timeout, retries=retries)
    except Exception as e:
        logger.warning(f"读取 ARP 表失败 ({ip}): {e}")
        return arp
    for oid_str, value in entries:
        parts = oid_str.lstrip('.').split('.')
        if len(parts) < 5:
            continue
        # 最后 4 段 = IP 地址
        ip_parts = parts[-4:]
        try:
            ip_addr = '.'.join(str(int(p)) for p in ip_parts)
        except ValueError:
            continue
        mac = normalize_mac(str(value))
        if mac and ip_addr:
            arp[ip_addr] = mac
    return arp


def _get_ap_mac_via_snmp(ap_ip: str, community: str, version: str,
                         timeout: int = 4, retries: int = 1) -> str:
    """直接 SNMP 读取 AP 自身 MAC（兜底反查用）。

    当 AC ARP 表、交换机 ARP 表都拿不到 AP MAC 时（AP 与网关跨网段、
    网关未纳入扫描等），直接 GET AP 自己的桥基 MAC / 接口物理地址。
    拿到 MAC 后即可走 _match_ap_in_index 的 MAC 反查（交换机 dot1d 表），
    不再依赖网关设备是否在扫描列表里。返回标准化 MAC 或 ''。
    """
    from utils.snmp_utils import snmp_get
    # dot1dBaseBridgeAddress：AP 桥基 MAC，通常是其上行口使用的 MAC
    # ifPhysAddress.1：ifIndex=1 接口物理地址（部分 AP 桥基 OID 不支持时兜底）
    oids = [
        '1.3.6.1.2.1.17.1.1.0',
        '1.3.6.1.2.1.2.2.1.6.1',
    ]
    for oid in oids:
        try:
            raw = snmp_get(ap_ip, community, version, oid, timeout=timeout)
        except Exception:
            raw = None
        if not raw:
            continue
        s = str(raw).strip().lower()
        if s.startswith('"') and s.endswith('"'):
            s = s[1:-1]
        if s.startswith('0x'):
            s = s[2:]
        hex_only = ''.join(c for c in s if c in '0123456789abcdef')
        if len(hex_only) == 12:
            mac = ':'.join(hex_only[i:i + 2] for i in range(0, 12, 2))
            return normalize_mac(mac)
    return ''


def _enrich_aps_from_ac_arp(aps: Dict[str, Dict], controller_ip: str,
                            community: str, version: str,
                            progress: Optional[Dict] = None) -> int:
    """用 AC 自身的 ARP 表把缺失 MAC 的 AP 补全。

    个别 MIB 表（或部分固件）拿不到 AP 的 MAC 列。
    AC 与所有 AP 都有 CAPWAP 通信，其 ARP 表必然包含 AP 的 IP -> MAC 映射。
    补全 MAC 后，后续 _match_ap_in_index 即可通过 MAC 匹配交换机端口。

    返回补全 MAC 的 AP 数量。
    """
    missing_mac = [ap for ap in aps.values() if not ap.get('mac') and ap.get('ip')]
    if not missing_mac:
        return 0
    _p_log(progress, f'读取 AC ARP 表，为 {len(missing_mac)} 个缺 MAC 的 AP 补全…')
    arp = _read_arp_table(controller_ip, community, version, timeout=10, retries=1)
    if not arp:
        _p_log(progress, f'AC ARP 表为空或读取失败，无法补全 MAC', 'warn')
        return 0
    _p_log(progress, f'AC ARP 表获取 {len(arp)} 条')
    enriched = 0
    for ap in missing_mac:
        mac = arp.get(ap['ip'])
        if mac:
            ap['mac'] = mac
            enriched += 1
    if enriched:
        _p_log(progress, f'通过 AC ARP 表补全 {enriched}/{len(missing_mac)} 个 AP 的 MAC')
    else:
        _p_log(progress, f'AC ARP 表中未匹配到任何 AP IP（可能 AP 在不同 VLAN/网段）', 'warn')
    return enriched


def _enrich_ap_names(aps: Dict[str, Dict], vendor: str, controller_ip: str,
                     community: str, version: str,
                     progress: Optional[Dict] = None) -> int:
    """为缺名称的 AP 补全 AC 内配置的名称（目前仅 H3C 需要）。

    H3C 的 hh3cDot11APObjectStatusTable 只有序列号/MAC/IP/状态，没有 AP 名称；
    名称在 hh3cDot11APObjectTable 的 hh3cDot11CurrAPName(.8) 列，
    索引与状态表相同，都是 AP 序列号（OCTET STRING 编码）。

    返回补全名称的 AP 数量。
    """
    missing = [ap for ap in aps.values() if not ap.get('name')]
    if vendor != 'h3c' or not missing:
        return 0
    _p_log(progress, f'读取 AC 内 AP 名称表，为 {len(missing)} 个缺名称的 AP 补全…')
    try:
        name_map = _walk_to_index_map(controller_ip, _H3C_AP_NAME_OID, community, version,
                                      timeout=10, retries=1)
    except Exception as e:
        _p_log(progress, f'读取 AC 内 AP 名称表失败: {e}', 'warn')
        return 0
    if not name_map:
        _p_log(progress, 'AC 内 AP 名称表为空（固件不支持），名称留空待后续补全', 'warn')
        return 0
    by_serial: Dict[str, str] = {}
    for index_suffix, raw_name in name_map.items():
        serial = _decode_octet_index(index_suffix)
        name = (raw_name or '').strip().strip('"')
        if serial and name:
            by_serial[serial] = name
    got = 0
    for ap in aps.values():
        if ap.get('name'):
            continue
        name = by_serial.get(ap.get('serial') or '')
        if not name and ap.get('_index'):
            # 兜底：状态表索引本身就是序列号（OCTET STRING），直接解码反查
            name = by_serial.get(_decode_octet_index(str(ap['_index'])))
        if name:
            ap['name'] = name
            got += 1
    if got:
        _p_log(progress, f'补全 {got}/{len(missing)} 个 AP 的 AC 内名称')
    else:
        _p_log(progress,
               f'未从 AC 名称表匹配到任何 AP（序列号格式可能不一致），名称留空', 'warn')
    return got


_ifname_cache: Dict[Tuple[str, str, str], List[Tuple[str, str]]] = {}


def _is_non_learned_mac(mac: str) -> bool:
    """过滤组播/广播/全零等不应参与 AP 匹配的 MAC。"""
    return mac.startswith(('ff:ff:ff', '01:00:5e', '33:33', '00:00:00'))


_POE_HINT_RE = re.compile(r'(poe|pwr|power\s*over\s*ethernet|inline\s*power)', re.IGNORECASE)


def _is_poe_switch(sw: Optional[Device]) -> bool:
    """启发式判断交换机是否支持 PoE（类型/名称/型号/品牌含 poe/pwr/power 等关键字）。"""
    if not sw:
        return False
    fields = ' '.join(str(x or '') for x in (
        sw.device_type, sw.name, sw.model, sw.brand, sw.manufacturer))
    return bool(_POE_HINT_RE.search(fields))


def _is_scan_candidate(sw: Optional[Device]) -> bool:
    """判断设备是否应进入 AP 端口匹配的交换机扫描列表。

    正式标记为 switch/router 的设备必然扫描；device_type 被误标为
    unknown/other/poe_switch、但名称/型号带 PoE 特征的接入交换机也要扫描，
    否则这些交换机整台被跳过，AP 即使在其 MAC 表里也匹配不到端口
    （实测案例：XMZ-2F-S5048poe device_type='unknown'，AP 的 MAC 学在其
    GE1/0/16 上却无法命中）。
    """
    if not sw or not sw.management_ip:
        return False
    return sw.device_type in ('switch', 'router') or _is_poe_switch(sw)


# 端口上 MAC 数达到该值视为级联/上行口，不可能是 AP 直连端口
CASCADE_PORT_MAC_THRESHOLD = 3


def _index_candidate(index_map: Dict[str, List[Dict]], key: str,
                     sw: Device, port: str, is_dot1d: bool, source: str,
                     port_macs: int, poe: bool) -> None:
    """向索引追加一个匹配候选；同交换机同端口保留更可信的来源（LLDP > MAC 表）。"""
    cand = {'sw': sw, 'port': str(port), 'is_dot1d': is_dot1d,
            'source': source, 'port_macs': port_macs, 'poe': poe}
    existing = index_map.get(key)
    if existing:
        for c in existing:
            if c['sw'].id == sw.id and c['port'] == str(port):
                if source == 'lldp' and c['source'] != 'lldp':
                    c.update(cand)
                return
    index_map.setdefault(key, []).append(cand)


def _candidate_score(cand: Dict) -> int:
    """候选评分：LLDP 直连 > 端口 MAC 数少（叶端口）> PoE 交换机 > 交换机类型。"""
    score = 0
    if cand.get('source') == 'lldp':
        score += 100
    # 端口 MAC 越少越像 AP 直连叶口（级联口已在构建时排除）
    port_macs = int(cand.get('port_macs') or 0)
    score += max(0, CASCADE_PORT_MAC_THRESHOLD - port_macs) * 10
    if cand.get('poe'):
        score += 30
    if cand['sw'].device_type == 'switch':
        score += 10
    return score


def _best_candidate(cands: Optional[List[Dict]]) -> Optional[Dict]:
    """从多个候选里选最优（评分相同取先加入者，保持确定性）。"""
    if not cands:
        return None
    return max(cands, key=_candidate_score)


def _walk_ifnames(ip: str, community: str, version: str) -> List[Tuple[str, str]]:
    """读取 ifName 表（带缓存，一个交换机索引阶段只走一次）。"""
    key = (ip, community, version)
    if key in _ifname_cache:
        return _ifname_cache[key]
    from utils.snmp_utils import snmp_walk
    rows = snmp_walk(ip, '1.3.6.1.2.1.31.1.1.1.1', community, version=version,
                    timeout=8, retries=1)
    _ifname_cache[key] = rows
    return rows


def _build_switch_index(switches, community: str, version: str,
                        progress=None, frac_start: float = 0.25,
                        frac_end: float = 0.60) -> Dict[str, Dict]:
    """一次性扫描所有交换机的 LLDP 邻居 + MAC 地址表 + ARP 表，构建反查索引。

    返回 {
        'mac':  {norm_mac: [候选,...]},     # 每个 MAC 可命中多台交换机/端口，匹配时择优
        'name': {lower_name: [候选,...]},   # LLDP sysname 反查
        'ip_mac': {ip_addr: norm_mac},          # 来自交换机 ARP 表，供 IP -> MAC -> port 链式反查
    }。
    级联/上行口（端口 MAC 数 >= CASCADE_PORT_MAC_THRESHOLD）不参与匹配，
    避免 AP 的 MAC 被上游非 PoE 交换机在级联口学到后错误匹配。
    只需 O(交换机数) 次 SNMP 遍历，供后续每个 AP 做 O(1) 反查。
    frac_start/frac_end 为该阶段在总体进度条上的占比区间（让进度条跨阶段单调递增）。
    """
    index: Dict[str, Dict] = {'mac': {}, 'name': {}, 'ip_mac': {}}
    total = len(switches)
    for i, sw in enumerate(switches):
        overall = int(frac_start * 100 + (frac_end - frac_start) * 100 * (i / total)) if total else int(frac_end * 100)
        _p_phase(progress, '扫描交换机端口索引', i, total, percent=overall)
        if not sw.management_ip:
            continue
        sw_ip = sw.management_ip
        # 逐交换机使用各自的 community（AC 控制器的 community 仅作兜底）。
        # 各交换机可能使用不同 community（如本例 192.168.4.11 用 gampublic），
        # 若统一用 AC 控制器的 community，对越权 OID 会被 SNMP agent 静默丢包 → 全部 Timeout。
        sw_comm = sw.snmp_community or community
        poe = _is_poe_switch(sw)
        # 策略 1：LLDP 邻居（端口名直接可得）
        try:
            from blueprints.topology import discover_lldp_neighbors
            neighbors = discover_lldp_neighbors(sw_ip, sw_comm)
            for n in neighbors:
                chassis = normalize_mac(str(n.get('remote_chassis') or ''))
                port = n.get('local_interface_name') or n.get('local_lldp_port')
                if chassis and port:
                    _index_candidate(index['mac'], chassis, sw, str(port), False, 'lldp', 0, poe)
                sysname = str(n.get('remote_sysname') or n.get('remote_sysdesc') or '').strip().lower()
                if sysname and port:
                    _index_candidate(index['name'], sysname, sw, str(port), False, 'lldp', 0, poe)
        except Exception as e:
            _p_log(progress, f'交换机 {sw.name} LLDP 读取失败: {e}', 'warn')
        # 策略 2：MAC 地址表（仅记录 dot1d 端口，命中时再解析 ifName）
        try:
            from blueprints.topology import get_mac_table
            mac_table = get_mac_table(sw_ip, sw_comm)
            # 先按 dot1d 端口统计可学习 MAC 数，识别级联/上行口
            port_mac_count: Dict[str, int] = {}
            port_macs: Dict[str, List[str]] = {}
            for m, dot1d in mac_table.items():
                nm2 = normalize_mac(m)
                if not nm2 or _is_non_learned_mac(nm2):
                    continue
                port_mac_count[dot1d] = port_mac_count.get(dot1d, 0) + 1
                port_macs.setdefault(dot1d, []).append(nm2)
            for dot1d, macs in port_macs.items():
                if port_mac_count[dot1d] >= CASCADE_PORT_MAC_THRESHOLD:
                    # 级联/上行口：同时学到大量下游设备 MAC，不可能是 AP 直连口
                    continue
                for nm2 in macs:
                    _index_candidate(index['mac'], nm2, sw, str(dot1d), True,
                                     'mac', port_mac_count[dot1d], poe)
        except Exception as e:
            _p_log(progress, f'交换机 {sw.name} MAC 表读取失败: {e}', 'warn')
        # 策略 3：ARP 表（IP -> MAC，后续链式反查 MAC -> port）
        try:
            arp = _read_arp_table(sw_ip, sw_comm, version, timeout=5, retries=1)
            for ip_addr, mac in arp.items():
                if ip_addr not in index['ip_mac']:
                    index['ip_mac'][ip_addr] = mac
        except Exception:
            pass  # ARP 读取失败不影响主流程
    _p_log(progress,
           f'交换机端口索引构建完成：覆盖 {len(index["mac"])} 个 MAC、'
           f'{len(index["name"])} 个名称、{len(index["ip_mac"])} 个 IP')
    return index


def _match_ap_in_index(mac: str, name: str, index: Dict[str, Dict],
                       community: str, version: str,
                       ap_ip: str = '') -> Tuple[Optional[Device], Optional[str]]:
    """在已构建的索引中反查 AP 的交换机与端口。

    匹配优先级：
      1. MAC 精确反查（LLDP chassis / MAC 地址表）
      2. AP 名称反查（LLDP sysname）
      3. IP -> MAC（交换机 ARP 表）-> MAC 索引反查（兜底）

    同一 MAC 可能被多台交换机学到（PoE 接入交换机的直连口 + 上游非 PoE
    交换机的级联口），因此从候选列表里按评分择优：LLDP 直连 > 叶端口
    （端口 MAC 数少）> PoE 交换机 > 普通交换机。
    """
    # 1) MAC
    norm_mac = normalize_mac(mac)
    if norm_mac and norm_mac in index['mac']:
        best = _best_candidate(index['mac'][norm_mac])
        if best:
            sw, port, is_dot1d = best['sw'], best['port'], best['is_dot1d']
            if is_dot1d:
                real = _resolve_dot1d_to_ifname(sw.management_ip, port,
                                                sw.snmp_community or community, version)
                if real:
                    port = real
            return sw, str(port)
    # 2) 名称
    if name:
        nm = name.strip().lower()
        if nm in index['name']:
            best = _best_candidate(index['name'][nm])
            if best:
                return best['sw'], str(best['port'])
    # 3) IP -> MAC -> port（兜底：AP 名称是序列号且 MIB 表无 MAC 时）
    if ap_ip:
        arp_mac = index.get('ip_mac', {}).get(ap_ip)
        if arp_mac and arp_mac in index['mac']:
            best = _best_candidate(index['mac'][arp_mac])
            if best:
                sw, port, is_dot1d = best['sw'], best['port'], best['is_dot1d']
                if is_dot1d:
                    real = _resolve_dot1d_to_ifname(sw.management_ip, port,
                                                    sw.snmp_community or community, version)
                    if real:
                        port = real
                return sw, str(port)
    return None, None


def _discover_aps_core(controller: Device,
                       community: Optional[str] = None,
                       version: Optional[str] = None,
                       progress: Optional[Dict] = None,
                       custom_base: Optional[str] = None) -> Dict:
    """核心发现逻辑（可被同步/异步调用）。progress 为任务字典时实时上报进度与日志。"""
    result = {
        'controller': controller.name,
        'vendor': 'auto',
        'total': 0,
        'created': 0,
        'updated': 0,
        'linked': 0,
        'stale_removed': 0,
        'errors': 0,
        'details': [],
    }
    ip = controller.management_ip or controller.ip_address
    if not ip:
        msg = '控制器无管理 IP，跳过'
        result['details'].append(msg)
        result['errors'] += 1
        _p_log(progress, msg, 'warn')
        return result

    community = community or controller.snmp_community or 'public'
    version = version or ('2c' if (controller.snmp_version or 2) == 2 else '1')

    # 1) 连通性探测：SNMP 不可达时明确报错，避免被静默吞成“0 个”
    _p_phase(progress, '探测 SNMP 连通性', percent=10)
    from utils.snmp_utils import snmp_get
    sys_name = snmp_get(ip, community, version, '1.3.6.1.2.1.1.5.0', timeout=5)
    if sys_name is None:
        sys_descr = snmp_get(ip, community, version, '1.3.6.1.2.1.1.1.0', timeout=5)
        if sys_descr is None:
            msg = (f'SNMP 不可达（IP={ip}, community={community!r}, version={version}）：'
                   f'请确认 AC 已开启 SNMP、community/版本正确且网络可达')
            result['details'].append(msg)
            result['errors'] += 1
            _p_log(progress, msg, 'error')
            return result
    _p_log(progress, f'SNMP 可达（sysName={sys_name!r}）')

    # 2) 厂商识别
    _p_phase(progress, '识别厂商', percent=15)
    vendor = _detect_vendor(controller, community, version)
    result['vendor'] = vendor
    tables = VENDOR_TABLES.get(vendor)
    if not tables:
        msg = (f'不支持的厂商: {vendor}（请在设备编辑页指定 controller_vendor 为 '
               f'auto/h3c/huawei/cisco/aruba/ruijie）')
        result['details'].append(msg)
        result['errors'] += 1
        _p_log(progress, msg, 'error')
        return result
    _p_log(progress, f'识别厂商: {vendor}')

    # 3) 遍历候选 MIB 表，第一套命中即用
    _p_phase(progress, '读取 AC AP 表', percent=25)
    aps: Dict[str, Dict] = {}
    candidates = list(tables)
    if custom_base:
        # 用户从诊断里拿到正确 OID 后，可直接作为第一候选使用（通用列映射）
        candidates.insert(0, {
            'base': str(custom_base).strip().rstrip('.'),
            'name': '2', 'ip': '3', 'mac': '1', 'serial': '5', 'status': '4',
            'online': {'1'}, '_custom': True,
        })
        _p_log(progress, f'使用自定义 MIB 基OID: {custom_base}')
    # H3C 等厂家 WLAN 表单条处理极慢（实测约 4 秒/条），整表 walk 可能需数分钟。
    # 发现任务在后台线程执行（不占用 HTTP 请求），故给足 total_timeout 避免被提前掐断，
    # 并用 on_line 实时上报已读取行数，让用户看到进度而非卡死。
    AP_TABLE_WALK_TIMEOUT = 1800  # 30 分钟上限，足够覆盖数百台 AP 的慢速 walk
    from utils.snmp_utils import SNMPWalkError
    _live = {'n': 0}
    for t in candidates:
        base = str(t['base'])
        _p_log(progress, f'开始读取 MIB 表 {base}（H3C 此表可能较大，请耐心等待…）', 'info')

        def _on_line(oid_str, value_str, _t=base):
            _live['n'] += 1
            if _live['n'] % 5 == 0:
                _p_log(progress, f'正在读取 AP 表 {_t}：已获取 {_live["n"]} 行…', 'info')

        try:
            rows = _walk_table(ip, base, community, version,
                               timeout=10, retries=1,
                               total_timeout=AP_TABLE_WALK_TIMEOUT,
                               on_line=_on_line, raise_on_error=True)
        except SNMPWalkError as e:
            _p_log(progress, f'MIB 表 {base} 读取失败: {e}', 'warn')
            result['details'].append(f'MIB 表 {base} 读取失败: {e}')
            continue
        if not rows:
            _p_log(progress, f'MIB 表 {base} 未返回数据（可能不适用此固件）', 'warn')
            result['details'].append(f'MIB 表 {base} 未返回数据（可能不适用此固件）')
            continue
        for index, cols in rows.items():
            mac, name, ap_ip, serial, status = _parse_ap_row(t, index, cols)
            key = mac or index
            ap = aps.setdefault(key, {
                'mac': mac, 'name': '', 'ip': '', 'serial': '', 'status': 'offline',
                '_index': index,
            })
            ap['mac'] = ap['mac'] or mac
            ap['name'] = ap['name'] or name
            ap['ip'] = ap['ip'] or ap_ip
            ap['serial'] = ap['serial'] or serial
            ap['_index'] = ap.get('_index') or index
            if status == 'online':
                ap['status'] = 'online'
        _p_log(progress, f'MIB 表 {t["base"]} 命中 {len(rows)} 行')
        result['details'].append(f'MIB 表 {t["base"]} 命中 {len(rows)} 行')
        break

    result['total'] = len(aps)
    if result['total'] == 0:
        msg = ('所有候选 MIB 表均未取到 AP：请核对厂商/固件，或在 AC 上用 '
               'snmpwalk 确认 AP 表 OID（可抓包后补充到 VENDOR_TABLES）')
        result['details'].append(msg)
        _p_log(progress, msg, 'warn')
        return result
    _p_log(progress, f'从 AC 读取到 {result["total"]} 个 AP')

    # 3.4) 补全 AP 名称：H3C 运行状态表没有名称列，索引还是序列号，
    #      需从 hh3cDot11APObjectTable 的 hh3cDot11CurrAPName(.8) 按序列号补全，
    #      保证资产名称显示 AC 内配置的名称而非序列号。
    _p_phase(progress, '读取 AC 内 AP 名称', percent=22)
    _enrich_ap_names(aps, vendor, ip, community, version, progress)

    # 3.5) ARP 补全 MAC：H3C 隧道表等无 MAC 列的 MIB 表会导致所有 AP 缺 MAC，
    #       无法匹配交换机端口。读 AC 自身 ARP 表，用 AP IP -> MAC 补全。
    _p_phase(progress, '通过 AC ARP 表补全 AP MAC', percent=23)
    _enrich_aps_from_ac_arp(aps, ip, community, version, progress)

    # 3.6) 兜底：AC ARP 仍缺 MAC 的 AP，直接 SNMP 读 AP 自身 MAC。
    #       适用场景：AP 与网关跨网段、网关未纳入扫描，导致 MAC 完全无法反查。
    #       拿到 MAC 后即可走 _match_ap_in_index 的 MAC 反查（交换机 dot1d 表），
    #       不再依赖网关设备是否在扫描列表里。
    missing_after = [ap for ap in aps.values() if not ap.get('mac') and ap.get('ip')]
    if missing_after:
        _p_log(progress, f'尝试直接 SNMP 读取 {len(missing_after)} 个缺 MAC AP 自身 MAC…', 'info')
        got = 0
        for ap in missing_after:
            mac = _get_ap_mac_via_snmp(ap['ip'], community, version)
            if mac:
                ap['mac'] = mac
                got += 1
        if got:
            _p_log(progress, f'通过 AP 自身 SNMP 补全 {got}/{len(missing_after)} 个 AP 的 MAC')
        else:
            _p_log(progress,
                   f'AP 自身 SNMP 未取到 MAC（AP 可能不响应 SNMP 或 community 不符，'
                   f'将仅建资产不连端口）', 'warn')

    # 4) 一次性构建交换机端口索引（避免逐 AP 扫描全部交换机）
    _p_phase(progress, '构建交换机端口索引', percent=25)
    switches = Device.query.filter(
        Device.management_ip.isnot(None),
        Device.id != controller.id,
    ).all()
    # 除正式 switch/router 外，还把 device_type 标错但带 PoE 特征的
    # 接入交换机纳入扫描（如 XMZ-2F-S5048poe，type=unknown）
    switches = [sw for sw in switches if _is_scan_candidate(sw)]
    _p_log(progress, f'待扫描交换机/路由设备共 {len(switches)} 台')
    switch_index = _build_switch_index(switches, community, version, progress, 0.25, 0.60)

    # 5) 逐 AP 建/更资产并匹配交换机端口（O(1) 反查）
    _p_phase(progress, '匹配 AP 端口并建立资产', 0, result['total'], percent=60)
    for i, (ap_key, ap) in enumerate(aps.items()):
        overall = 60 + int(40 * (i + 1) / result['total']) if result['total'] else 100
        _p_phase(progress, '匹配 AP 端口并建立资产', i + 1, result['total'], percent=overall)
        ap_mac = ap['mac']
        try:
            device = _upsert_ap_device(
                mac=ap_mac, name=ap['name'], ip=ap['ip'], serial=ap['serial'],
                status=ap['status'], vendor=vendor,
            )
            if device is None:
                result['errors'] += 1
                continue
            if device._ac_just_created:  # type: ignore[attr-defined]
                result['created'] += 1
            else:
                result['updated'] += 1

            # 在已构建索引中反查 PoE 交换机端口
            switch_dev, switch_port = _match_ap_in_index(
                ap_mac, ap['name'], switch_index, community, version, ap_ip=ap.get('ip', ''))
            if switch_dev and switch_port:
                # 清理该 AP 旧的、由 AC 发现但指向其它交换机/端口的 edge_ap 连接，
                # 避免早期版本误匹配到非 PoE 交换机的级联口后残留错误拓扑
                removed = _replace_stale_ap_links(device, switch_dev, switch_port)
                if removed:
                    result['stale_removed'] += removed
                    _p_log(progress,
                           f'清理 {device.name} 旧的错误 AP 连接 {removed} 条（改指 '
                           f'{switch_dev.name}:{switch_port}）', 'warn')
                created_link = _upsert_ap_connection(switch_dev, switch_port, device)
                if created_link:
                    result['linked'] += 1
                line = f"{device.name} ({ap_mac or ap['name']}) -> {switch_dev.name}:{switch_port}"
                result['details'].append(line)
                _p_log(progress, f'匹配端口：{line}', 'info')
            else:
                ip_info = f", IP={ap.get('ip', '')}" if ap.get('ip') else ""
                line = f"{device.name} ({ap_mac or ap['name']}{ip_info}) 未匹配到交换机端口（仅建资产，无连接）"
                result['details'].append(line)
                _p_log(progress, line, 'warn')
        except Exception as e:  # 单条 AP 失败不影响其余
            logger.exception(f"AC 发现 AP {ap_mac or ap_key} 异常: {e}")
            result['errors'] += 1
            result['details'].append(f"{ap_mac or ap_key} 处理异常: {e}")
            _p_log(progress, f"{ap_mac or ap_key} 处理异常: {e}", 'error')

    db.session.commit()
    _p_phase(progress, '完成', result['total'], result['total'])
    _p_log(progress,
           f'发现完成：共 {result["total"]} 个 AP，新建 {result["created"]}，'
           f'更新 {result["updated"]}，匹配端口 {result["linked"]}，'
           f'清理旧错误连接 {result["stale_removed"]}，异常 {result["errors"]}')
    return result


def discover_aps_from_controller(controller: Device,
                                 community: Optional[str] = None,
                                 version: Optional[str] = None,
                                 custom_base: Optional[str] = None) -> Dict:
    """同步入口（供调度器 discover_all_controllers 调用）。无进度上报。"""
    return _discover_aps_core(controller, community=community, version=version,
                              progress=None, custom_base=custom_base)


# ---------------------------------------------------------------------------
# 异步任务：后台线程跑发现，前端轮询状态
# ---------------------------------------------------------------------------
def start_ac_discovery(controller_id: int,
                       community: Optional[str] = None,
                       version: Optional[str] = None,
                       custom_base: Optional[str] = None) -> str:
    """启动一次异步 AP 发现，立即返回 job_id。前端用 discover_aps_status 轮询。"""
    job_id = uuid.uuid4().hex[:12]
    AC_DISCOVERY_JOBS[job_id] = {
        'phase': '初始化', 'current': 0, 'total': 0, 'percent': 0,
        'log': [], 'done': False, 'failed': False, 'result': None, 'error': None,
        'started_at': time.time(), 'finished_at': None,
    }
    app = current_app._get_current_object()
    t = threading.Thread(
        target=_run_ac_discovery_job,
        args=(job_id, controller_id, community, version, custom_base, app),
        daemon=True,
    )
    t.start()
    logger.info(f"启动异步 AC AP 发现 job={job_id} controller_id={controller_id}")
    return job_id


def _run_ac_discovery_job(job_id: str, controller_id: int,
                          community: Optional[str], version: Optional[str],
                          custom_base: Optional[str], app):
    """后台线程：在应用上下文内执行核心发现逻辑并回写进度。"""
    data = AC_DISCOVERY_JOBS.get(job_id)
    if data is None:
        return
    try:
        with app.app_context():
            controller = Device.query.get(controller_id)
            if not controller:
                raise ValueError(f'控制器不存在 (id={controller_id})')
            result = _discover_aps_core(controller, community=community, version=version,
                                        progress=data, custom_base=custom_base)
            data['result'] = result
            data['done'] = True
            data['percent'] = 100
            data['phase'] = '完成'
    except Exception as e:
        logger.exception(f"异步 AC 发现异常 job={job_id}: {e}")
        data['error'] = str(e)
        data['failed'] = True
        data['done'] = True
        data['phase'] = '失败'
        _p_log(data, f'发现失败: {e}', 'error')
    finally:
        data['finished_at'] = time.time()


def get_ac_job(job_id: str) -> Optional[Dict]:
    return AC_DISCOVERY_JOBS.get(job_id)


# ---------------------------------------------------------------------------
# 资产/连接建库
# ---------------------------------------------------------------------------
def _upsert_ap_device(mac: str, name: str, ip: str, serial: str,
                      status: str, vendor: str) -> Optional[Device]:
    """按 MAC（或 IP）查找/创建 AP 资产。返回设备对象；通过 _ac_just_created 标记是否新建。"""
    device = None
    if mac and ':' in mac:
        device = Device.query.filter_by(mac_address=mac).first()
    if device is None and ip:
        device = Device.query.filter(
            (Device.management_ip == ip) | (Device.ip_address == ip)
        ).first()
    if device is None and serial:
        device = Device.query.filter_by(serial_number=serial).first()

    if device is None:
        device = Device(
            name=name or f"AP-{mac.replace(':', '')[-6:]}",
            device_type='ap',
            mac_address=mac if ':' in mac else None,
            management_ip=ip or None,
            ip_address=ip or None,
            serial_number=serial or None,
            brand=vendor,
            status=status,
        )
        db.session.add(device)
        db.session.flush()
        device._ac_just_created = True  # type: ignore[attr-defined]
    else:
        device._ac_just_created = False  # type: ignore[attr-defined]
        changed = False
        if device.device_type in (None, '', 'unknown', 'other'):
            device.device_type = 'ap'
            changed = True
        # 历史数据里曾把 H3C 状态表的序列号索引当成名称入库，
        # 现名是“序列号样式”时同样允许被 AC 内配置的名称覆盖
        if (name and device.name != name
                and (not device.name or device.name.startswith('AP-')
                     or device.name == 'unknown'
                     or _looks_like_serial(device.name)
                     or (serial and device.name == serial))):
            device.name = name
            changed = True
        if ip and not device.management_ip and not device.ip_address:
            device.management_ip = ip
            device.ip_address = ip
            changed = True
        if serial and not device.serial_number:
            device.serial_number = serial
            changed = True
        # 修复后状态表能直接提供 MAC；已存在 AP 缺 MAC 时回填，
        # 后续才能稳定按 MAC 匹配 PoE 交换机端口
        if mac and ':' in mac and not device.mac_address:
            device.mac_address = mac
            changed = True
        if status:
            device.status = status
            changed = True
        if not device.brand:
            device.brand = vendor
            changed = True
        if changed:
            db.session.flush()
    return device


def _replace_stale_ap_links(ap_dev: Device, switch_dev: Device, switch_port: str) -> int:
    """删除该 AP 上由 AC 发现、但指向其它交换机/端口的旧 edge_ap 连接。

    旧版本曾把 AP 错误匹配到非 PoE 交换机的级联口；当本次匹配到更可信的
    直连端口时，把残留的错误连接清掉，避免同一 AP 出现多条上行或错误拓扑。
    仅处理 discovered_by='AC' 且 link_role='edge_ap' 的连接，不影响其它协议发现的链路。
    返回删除条数。
    """
    stale = ConnectionPath.query.filter(
        ConnectionPath.link_role == 'edge_ap',
        ConnectionPath.discovered_by == 'AC',
        db.or_(
            ConnectionPath.source_device_id == ap_dev.id,
            ConnectionPath.target_device_id == ap_dev.id,
        ),
    ).all()
    removed = 0
    for conn in stale:
        if conn.source_device_id == ap_dev.id:
            other_dev_id, ap_port = conn.target_device_id, conn.source_port
        elif conn.target_device_id == ap_dev.id:
            other_dev_id, ap_port = conn.source_device_id, conn.target_port
        else:
            continue
        # 与本次匹配结果一致（同交换机同端口）的连接保留并复用
        if other_dev_id == switch_dev.id and ap_port == switch_port:
            continue
        db.session.delete(conn)
        removed += 1
    if removed:
        db.session.flush()
    return removed


def _upsert_ap_connection(switch_dev: Device, switch_port_name: str,
                          ap_dev: Device) -> bool:
    """建立/更新 交换机端口<->AP 的连接（link_role=edge_ap），复用双向归一化+去重。"""
    switch_port = Interface.query.filter_by(
        device_id=switch_dev.id, name=switch_port_name
    ).first()

    # 双向归一化：小 ID 为 source
    if switch_dev.id > ap_dev.id:
        real_src, real_src_port = ap_dev, None
        real_src_port_name = 'unknown'
        real_tgt, real_tgt_port = switch_dev, switch_port
        real_tgt_port_name = switch_port_name
    else:
        real_src, real_src_port = switch_dev, switch_port
        real_src_port_name = switch_port_name
        real_tgt, real_tgt_port = ap_dev, None
        real_tgt_port_name = 'unknown'

    existing = ConnectionPath.query.filter(
        db.or_(
            db.and_(
                ConnectionPath.source_device_id == real_src.id,
                ConnectionPath.source_port == real_src_port_name,
                ConnectionPath.target_device_id == real_tgt.id,
                ConnectionPath.target_port == real_tgt_port_name,
            ),
            db.and_(
                ConnectionPath.source_device_id == real_tgt.id,
                ConnectionPath.source_port == real_tgt_port_name,
                ConnectionPath.target_device_id == real_src.id,
                ConnectionPath.target_port == real_src_port_name,
            ),
        )
    ).first()

    if existing:
        existing.discovery_time = db.func.now()
        existing.last_seen = db.func.now()
        existing.link_status = 'active'
        existing.discovered_by = 'AC'
        existing.discovery_protocol = 'CAPWAP'
        existing.auto_discovered = True
        existing.neighbor_managed = True
        existing.link_role = 'edge_ap'
        existing.confidence = 100
        db.session.flush()
        return False

    conn = ConnectionPath(
        source_device_id=real_src.id,
        source_interface_id=real_src_port.id if real_src_port else None,
        source_port=real_src_port_name,
        target_device_id=real_tgt.id,
        target_interface_id=real_tgt_port.id if real_tgt_port else None,
        target_port=real_tgt_port_name,
        connection_type='physical',
        link_status='active',
        discovered_by='AC',
        discovery_protocol='CAPWAP',
        discovery_time=db.func.now(),
        last_seen=db.func.now(),
        auto_discovered=True,
        neighbor_managed=True,
        link_role='edge_ap',
        confidence=100,
    )
    db.session.add(conn)
    db.session.flush()
    return True


def discover_all_controllers() -> List[Dict]:
    """对所有标记为无线控制器的设备执行发现，供定时任务调用。"""
    controllers = Device.query.filter_by(is_wireless_controller=True).all()
    results = []
    for c in controllers:
        try:
            results.append(discover_aps_from_controller(c))
        except Exception as e:
            logger.exception(f"控制器 {c.name} AP 发现失败: {e}")
            results.append({'controller': c.name, 'error': str(e), 'total': 0,
                            'created': 0, 'updated': 0, 'linked': 0, 'errors': 1,
                            'details': [str(e)]})
    return results


def discover_all_controllers_task(app):
    """调度任务入口：在应用上下文内对所有无线控制器执行 AP 发现。"""
    with app.app_context():
        return discover_all_controllers()
