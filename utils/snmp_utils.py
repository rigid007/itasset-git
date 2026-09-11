# snmp_utils.py
"""SNMP utility functions: get, walk, device info, interface discovery."""
import re
import time
import logging
from typing import List, Optional, Tuple
from pysnmp.hlapi import (
    SnmpEngine,
    CommunityData,
    UsmUserData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    getCmd,
    nextCmd,
    bulkCmd,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmDESPrivProtocol,
    usmAesCfb128Protocol,
)
from datetime import datetime

from extensions import db
from models import Device, Interface
from utils.vendor_oid_map import identify_by_sys_object_id, is_infra_agent
from utils.model_type_map import infer_from_model

logger = logging.getLogger(__name__)

SNMP_TIMEOUT = 3


class SnmpClient:
    """Pure Python SNMP client used as a replacement for net-snmp command line tools.

    Supports SNMP v1, v2c and v3. Returned OID values are normalized to strings.
    """

    def __init__(self, ip, community="public", version="2c", port=161,
                 timeout=SNMP_TIMEOUT, retries=1, v3_params=None):
        self.ip = str(ip or "").strip()
        self.community = community or "public"
        self.port = int(port or 161)
        self.timeout = float(timeout or SNMP_TIMEOUT)
        self.retries = int(retries or 1)
        self.v3_params = v3_params or {}
        self.version = self._normalize_version(version)

    @staticmethod
    def _normalize_version(version):
        """Return SNMP protocol integer used internally: 0=v1, 1=v2c, 3=v3."""
        if isinstance(version, int):
            return 0 if version == 1 else (3 if version == 3 else 1)
        v = str(version or "2c").strip().lower().lstrip("v")
        if v in ("1", "v1"):
            return 0
        if v in ("2c", "2", "v2c", "v2"):
            return 1
        if v in ("3", "v3"):
            return 3
        return 1

    @staticmethod
    def _auth_protocol(name):
        n = str(name or "").upper()
        if "SHA" in n:
            return usmHMACSHAAuthProtocol
        return usmHMACMD5AuthProtocol

    @staticmethod
    def _priv_protocol(name):
        n = str(name or "").upper()
        if "AES" in n or "CFB128" in n:
            return usmAesCfb128Protocol
        if "DES" in n:
            return usmDESPrivProtocol
        return None

    def _security(self):
        if self.version == 3:
            p = self.v3_params
            return UsmUserData(
                p.get("username") or "",
                p.get("auth_password") or None,
                p.get("priv_password") or None,
                authProtocol=self._auth_protocol(p.get("auth_protocol", "MD5")),
                privProtocol=self._priv_protocol(p.get("priv_protocol", "DES")),
            )
        mp_model = 0 if self.version == 0 else 1
        return CommunityData(self.community, mpModel=mp_model)

    def _transport(self):
        return UdpTransportTarget((self.ip, self.port), timeout=self.timeout, retries=self.retries)

    @staticmethod
    def _value_to_str(value):
        if value is None:
            return ""
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="ignore")
            except Exception:
                return str(value)
        try:
            pp = value.prettyPrint()
        except Exception:
            pp = str(value)
        if isinstance(pp, bytes):
            try:
                return pp.decode("utf-8", errors="ignore")
            except Exception:
                return str(pp)
        return str(pp)

    @staticmethod
    def _oid_to_str(oid):
        if hasattr(oid, "prettyPrint"):
            try:
                return str(oid.prettyPrint())
            except Exception:
                pass
        return str(oid)

    def get(self, oid):
        """Run a single SNMP GET and return a normalized primitive value."""
        if not self.ip:
            return None
        try:
            iterator = getCmd(
                SnmpEngine(),
                self._security(),
                self._transport(),
                ContextData(),
                ObjectType(ObjectIdentity(str(oid))),
            )
            error_indication, error_status, error_index, var_binds = next(iterator)
        except Exception as exc:
            logger.debug("SNMP get failed %s %s: %s", self.ip, oid, exc)
            return None
        if error_indication or error_status:
            logger.debug("SNMP get error %s %s: %s %s", self.ip, oid, error_indication, error_status)
            return None
        if not var_binds:
            return None
        return self._value_to_str(var_binds[0][1])

    def walk(self, oid, on_line=None, total_timeout=None):
        """Run SNMP WALK using nextCmd and return [(oid, value), ...]."""
        results = []
        if not self.ip:
            return results
        base_oid = str(oid).lstrip(".")
        started = time.time()
        deadline = float(total_timeout) if total_timeout else max(60, self.timeout * (self.retries + 1) * 5)
        try:
            iterator = nextCmd(
                SnmpEngine(),
                self._security(),
                self._transport(),
                ContextData(),
                ObjectType(ObjectIdentity(str(oid))),
                lexicographicMode=True,
            )
            for error_indication, error_status, error_index, var_binds in iterator:
                if time.time() - started > deadline:
                    break
                if error_indication or error_status:
                    break
                if not var_binds:
                    break
                outside = False
                for var_oid, value in var_binds:
                    oid_str = self._oid_to_str(var_oid).lstrip(".")
                    if not oid_str.startswith(base_oid):
                        outside = True
                        break
                    value_str = self._value_to_str(value)
                    results.append((oid_str, value_str))
                    if on_line is not None:
                        on_line(oid_str, value_str)
                if outside:
                    break
        except Exception as exc:
            logger.debug("SNMP walk failed %s %s: %s", self.ip, oid, exc)
        return results

    def bulkwalk(self, oid, non_repeaters=0, max_repetitions=25, total_timeout=None):
        """Run SNMP BULKWALK and return [(oid, value), ...]."""
        results = []
        if not self.ip:
            return results
        base_oid = str(oid).lstrip(".")
        started = time.time()
        deadline = float(total_timeout) if total_timeout else max(60, self.timeout * (self.retries + 1) * 5)
        try:
            iterator = bulkCmd(
                SnmpEngine(),
                self._security(),
                self._transport(),
                ContextData(),
                int(non_repeaters),
                int(max_repetitions),
                ObjectType(ObjectIdentity(str(oid))),
            )
            for error_indication, error_status, error_index, var_binds in iterator:
                if time.time() - started > deadline:
                    break
                if error_indication or error_status:
                    break
                if not var_binds:
                    break
                outside = False
                for var_oid, value in var_binds:
                    oid_str = self._oid_to_str(var_oid).lstrip(".")
                    if not oid_str.startswith(base_oid):
                        outside = True
                        break
                    results.append((oid_str, self._value_to_str(value)))
                if outside:
                    break
        except Exception as exc:
            logger.debug("SNMP bulkwalk failed %s %s: %s", self.ip, oid, exc)
        return results


class SNMPWalkError(Exception):
    """SNMP WALK 硬失败（命令不存在 / 超时 / 进程非零退出）。

    与“OID 不存在返回空列表”区分：后者是正常结果（该 MIB 不适用此固件），
    前者是环境/网络问题，应当显式上报，避免被静默吞成“0 个”。
    """
    pass


def _parse_walk_line(line: str, base_oid: str):
    """解析 snmpwalk -On 的一行输出，返回 (oid_str, value_str) 或 None。

    跳过“No Such Object/Instance”、“No more variables”等非数据行。
    """
    line = line.strip()
    if not line or '=' not in line:
        return None
    if 'No Such Instance' in line or 'No Such Object' in line or 'No more variables' in line:
        return None
    oid_part, value_part = line.split('=', 1)
    oid_str = oid_part.strip()
    value_part = value_part.strip()
    if ': ' in value_part:
        value_str = value_part.split(': ', 1)[1]
    else:
        value_str = value_part
    if value_str.startswith('"') and value_str.endswith('"'):
        value_str = value_str[1:-1]
    value_str = _decode_hex_value(value_str)
    if not oid_str.startswith(base_oid):
        return None
    return oid_str, value_str


def _decode_hex_value(value: str) -> str:
    """将snmp输出的hex格式（如'47 41 4D'）解码为中文字符串，非hex格式原样返回。

    重要：6 对 hex（6 字节）几乎一定是 MAC 地址（如 'AA BB CC DD EE FF'），
    不能当文本解码——GBK 会把 \xAA\xBB\xCC\xDD\xEE\xFF 解码成 3 个汉字，
    导致 ARP 表等场景的 MAC 被完全破坏。遇到 6 对 hex 时直接返回标准 MAC 格式。
    """
    stripped = value.strip()
    # 6 对 hex = MAC 地址，不做文本解码
    if re.match(r'^[0-9a-fA-F]{2}(?:\s[0-9a-fA-F]{2}){5}$', stripped):
        parts = stripped.split()
        return ':'.join(p.lower() for p in parts)
    # 检查是否为 space-separated hex pairs (至少两对)
    if not re.match(r'^[0-9a-fA-F]{2}(?:\s[0-9a-fA-F]{2})+$', stripped):
        return value
    try:
        raw = bytes.fromhex(stripped.replace(' ', ''))
        # 优先尝试GBK/GB2312（网络设备sysName多为此编码），最后尝试UTF-8
        # 避免 C2 A5（GBK:楼, UTF-8:¥）等字节在UTF-8下误解码
        for enc in ('gbk', 'gb2312', 'gb18030', 'utf-8', 'utf-16-le'):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        # 全部解码失败，返回原始hex串
        return value
    except Exception:
        return value


def snmp_get(ip: str, community: str, version: str, oid: str,
             timeout: int = SNMP_TIMEOUT):
    """Run SNMP GET through the pure Python SnmpClient."""
    client = SnmpClient(ip, community=community, version=version, timeout=timeout)
    value = client.get(oid)
    if value is None:
        return None
    if isinstance(value, str):
        value = _decode_hex_value(value)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].strip()
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
def parse_if_status(value) -> str:
    """把 snmp_walk 返回的接口状态值规范化为 up/down/unknown。

    snmp_walk 依赖外部 snmpwalk 命令，INTEGER 枚举会带文本，如 'up(1)'/'down(2)'；
    直接与 '1'/'2' 比较永远不匹配，必须取文本前缀。
    """
    s = str(value or '').strip().lower()
    if s.startswith('up'):
        return 'up'
    if s.startswith('down'):
        return 'down'
    if s in ('1', '1.0'):
        return 'up'
    if s in ('2', '2.0'):
        return 'down'
    return 'unknown'


def snmp_walk(ip: str, oid: str, community: str = 'public',
              version: str = '2c', timeout: int = 5,
              retries: int = 2, total_timeout: Optional[int] = None,
              on_line=None, raise_on_error: bool = False) -> List[Tuple[str, str]]:
    """Run SNMP WALK through the pure Python SnmpClient."""
    client = SnmpClient(ip, community=community, version=version, timeout=timeout, retries=retries)
    try:
        return client.walk(oid, on_line=on_line, total_timeout=total_timeout)
    except Exception as exc:
        logger.warning("snmp_walk failed %s %s: %s", ip, oid, exc)
        if raise_on_error:
            raise SNMPWalkError(str(exc))
        return []
def walk_interfaces(ip, community='public', timeout=5):
    """Return {ifIndex: ifName} using IF-MIB ifName and ifDescr fallback."""
    result = {}
    client = SnmpClient(ip, community=community, version='2c', timeout=timeout)
    ifname_items = client.walk('1.3.6.1.2.1.31.1.1.1.1')
    ifdescr_items = client.walk('1.3.6.1.2.1.2.2.1.2') if not ifname_items else []
    items = ifname_items or ifdescr_items
    for oid_str, value in items:
        parts = oid_str.split('.')
        try:
            ifindex = int(parts[-1])
        except (ValueError, IndexError):
            continue
        value = _decode_hex_value(value)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        result[ifindex] = value.strip()
    return result
def clean_snmp_device_name(name: str, ip: str = '') -> str:
    """清理SNMP设备名称：hex→中文解码、去引号、检测无效名称"""
    name = (name or '').strip()
    # hex格式解码（snmpget对含中文的OCTET STRING输出为hex）
    name = _decode_hex_value(name)
    # 去除两端引号
    while len(name) >= 2 and name.startswith('"') and name.endswith('"'):
        name = name[1:-1].strip()
    if not name:
        return f'设备_{ip}' if ip else '未知设备'

    # 检测纯十六进制无效名称（MAC地址/序列号/hex编码但无法识别编码的fallback）
    hex_only = re.sub(r'[^0-9a-fA-F]', '', name)
    if len(hex_only) >= 10 and len(hex_only) <= 40:
        non_hex_count = sum(1 for c in name if c not in '0123456789abcdefABCDEF:-. ')
        if non_hex_count == 0:
            return f'设备_{ip}' if ip else name
    return name


def snmp_get_device_info(ip, community='public', version='2c', timeout=2, retries=1):
    """获取设备的SNMP基本信息 (sysDescr, sysName, sysLocation, sysObjectID)"""
    start = time.time()
    try:
        sys_name = snmp_get(ip, community, version, '1.3.6.1.2.1.1.5.0', timeout)
        if sys_name is None:
            logger.debug(f"SNMP 无响应 {ip}")
            return False, {}
        sys_name = clean_snmp_device_name(str(sys_name), ip)
        sys_descr = snmp_get(ip, community, version, '1.3.6.1.2.1.1.1.0', timeout) or ''
        sys_location = snmp_get(ip, community, version, '1.3.6.1.2.1.1.6.0', timeout) or ''
        sys_object_id = snmp_get(ip, community, version, '1.3.6.1.2.1.1.2.0', timeout) or ''
        info = {
            'ip': ip, 'sys_name': str(sys_name).strip(),
            'sys_descr': str(sys_descr).strip(),
            'sys_location': str(sys_location).strip(),
            'sys_object_id': str(sys_object_id).strip(),
            'snmp_community': community, 'snmp_version': version,
            'discovered_at': datetime.utcnow().isoformat()
        }
        logger.debug(f"SNMP 获取成功 {ip}: {info['sys_name']} 耗时 {time.time()-start:.2f}s")
        return True, info
    except Exception as e:
        logger.error(f"SNMP 获取异常 {ip}: {e}")
        return False, {}


def scan_ip_with_snmp(
    ip, community='public', version='2c', timeout=3, retries=1,
    on_conflict='update', update_fields=None
):
    """通过SNMP扫描设备信息并根据名称和IP的唯一性进行保存或更新"""
    scan_result = _scan_ip_with_snmp_only(ip, community, version, timeout, retries)
    if not scan_result['success']:
        return {
            'success': False, 'device_id': None, 'action': 'failed',
            'message': f"SNMP 扫描失败: {scan_result.get('error_detail', '无响应')}", 'device': None
        }
    sys_name = scan_result.get('sys_name', f'设备_{ip}')
    manufacturer = scan_result.get('manufacturer', '')
    device_type = scan_result.get('device_type', '')
    model = scan_result.get('model', '')
    sys_descr = scan_result.get('sys_descr', '')
    sys_object_id = scan_result.get('sys_object_id', '')

    candidate = build_discovery_candidate(scan_result)
    match = match_device_candidate(candidate)
    matched_device = match.get('device')
    if matched_device and matched_device.management_ip != ip and matched_device.name != sys_name:
        existing_by_name = matched_device
    else:
        existing_by_name = Device.query.filter_by(name=sys_name).first()
    existing_by_ip = Device.query.filter_by(management_ip=ip).first()

    conflict = None
    if existing_by_name and existing_by_ip:
        if existing_by_name.id == existing_by_ip.id:
            existing_device = existing_by_name
        else:
            conflict = 'both'
    elif existing_by_name:
        conflict = 'name'
        existing_device = existing_by_name
    elif existing_by_ip:
        conflict = 'ip'
        existing_device = existing_by_ip
    else:
        existing_device = None

    if existing_device:
        if conflict == 'both':
            msg = (f"严重冲突：名称 '{sys_name}' 属于设备 ID {existing_by_name.id}，"
                   f"IP '{ip}' 属于设备 ID {existing_by_ip.id}，无法自动处理。")
            if on_conflict == 'error':
                return {'success': False, 'action': 'failed', 'message': msg, 'device': None}
            elif on_conflict == 'skip':
                return {'success': True, 'action': 'skipped', 'message': msg, 'device': None}
            else:
                return {'success': False, 'action': 'failed', 'message': msg, 'device': None}
        if (conflict == 'name' and existing_device.management_ip == ip) or \
           (conflict == 'ip' and existing_device.name == sys_name):
            action = 'update'
        else:
            if on_conflict == 'skip':
                msg = f"设备名称 '{sys_name}' 或 IP '{ip}' 已被其他设备使用 (ID: {existing_device.id})，已跳过"
                return {'success': True, 'action': 'skipped', 'message': msg, 'device': existing_device}
            elif on_conflict == 'error':
                msg = f"设备名称 '{sys_name}' 或 IP '{ip}' 已被其他设备使用 (ID: {existing_device.id})"
                return {'success': False, 'action': 'failed', 'message': msg, 'device': existing_device}
            else:
                msg = f"冲突且非同一设备，无法安全更新，请先手动处理重复数据 (ID: {existing_device.id})"
                return {'success': False, 'action': 'failed', 'message': msg, 'device': existing_device}
    else:
        action = 'create'

    try:
        if action == 'create':
            device = Device(
                name=sys_name, management_ip=ip, device_type=device_type,
                manufacturer=manufacturer, model=model, snmp_community=community,
                snmp_version=version, description=sys_descr[:500] if sys_descr else None,
                status='unknown',
                discovery_source='snmp',
                discovery_confidence=match.get('score', 100),
                approval_status='review' if match.get('decision') == 'create' else 'approved',
                last_seen=datetime.utcnow(),
                managed_by='self')
            db.session.add(device)
            db.session.commit()
            msg = f"成功创建设备: {sys_name} ({ip})"
        else:
            device = existing_device
            if update_fields is None:
                device.name = sys_name
                device.management_ip = ip
                device.device_type = device_type
                device.manufacturer = manufacturer
                device.model = model
                device.snmp_community = community
                device.snmp_version = version
                device.description = sys_descr[:500] if sys_descr else None
                device.discovery_source = 'snmp'
                device.discovery_confidence = match.get('score', 100)
                device.last_seen = datetime.utcnow()
                device.managed_by = device.managed_by or 'self'
            else:
                if 'name' in update_fields: device.name = sys_name
                if 'management_ip' in update_fields: device.management_ip = ip
                if 'device_type' in update_fields: device.device_type = device_type
                if 'manufacturer' in update_fields: device.manufacturer = manufacturer
                if 'model' in update_fields: device.model = model
                if 'snmp_community' in update_fields: device.snmp_community = community
                if 'snmp_version' in update_fields: device.snmp_version = version
                if 'description' in update_fields: device.description = sys_descr[:500] if sys_descr else None
            db.session.commit()
            msg = f"成功更新设备: {sys_name} ({ip})"
        return {'success': True, 'device_id': device.id, 'action': action, 'message': msg, 'device': device,
                'candidate': candidate, 'match': {k: v for k, v in match.items() if k != 'device'}}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'device_id': None, 'action': 'failed', 'message': f"数据库操作失败: {str(e)}", 'device': None}


def _scan_ip_with_snmp_only(ip, community='public', version='2c', timeout=3, retries=1):
    """扫描单个IP的SNMP信息，返回设备信息字典"""
    success, info = snmp_get_device_info(ip, community, version, timeout, retries)
    if not success:
        return {'success': False, 'error': 'SNMP查询失败', 'error_detail': '无响应'}
    device_type, brand, model = infer_device_type_from_snmp(
        sys_descr=info.get('sys_descr', ''),
        sys_object_id=info.get('sys_object_id', ''),
        sys_name=info.get('sys_name', '')
    )
    return {
        'success': True, 'ip': ip, 'sys_name': info.get('sys_name', f'设备_{ip}'),
        'sys_descr': info.get('sys_descr', ''), 'sys_object_id': info.get('sys_object_id', ''),
        'manufacturer': brand, 'device_type': device_type, 'model': model,
        'snmp_community': community, 'snmp_version': version
    }


def infer_device_type_from_snmp(sys_descr: str, sys_object_id: str = '', sys_name: str = '') -> tuple:
    """根据 SNMP 信息推断设备类型、品牌、型号"""
    device_type = 'unknown'
    brand = ''
    model = ''
    sys_descr = (sys_descr or '').strip()
    sys_name = (sys_name or '').strip()
    sys_oid = (sys_object_id or '').strip()
    lower_desc = sys_descr.lower()
    lower_name = sys_name.lower()
    # P0-2: sysObjectID 企业前缀识别（IANA PEN，最长前缀优先），先于 sysDescr 关键词
    oid_ident = identify_by_sys_object_id(sys_oid, sys_descr)
    oid_brand = oid_ident['brand']

    if sys_oid.startswith('1.3.6.1.4.1.25506') or 'h3c' in lower_desc:
        brand = 'H3C'
        for pat in [r'H3C\s+(S\d{4}[A-Za-z0-9\-_/.]*)', r'H3C\s+(MSR\d+[A-Za-z0-9\-_/.]*)', r'H3C\s+([A-Z]{2,}\d+[A-Za-z0-9\-_/.]*)']:
            match = re.search(pat, sys_descr, re.IGNORECASE)
            if match:
                model = match.group(1)
                break
        if not model:
            alt = re.search(r'\b([A-Z]\d+[A-Za-z0-9\-_/.]*)', sys_descr)
            if alt:
                model = alt.group(1)
        if any(kw in lower_desc or kw in lower_name for kw in ['switch', '交换机', 's5130', 's5700']):
            device_type = 'switch'
        elif any(kw in lower_desc or kw in lower_name for kw in ['router', '路由', 'msr']):
            device_type = 'router'
        elif any(kw in lower_desc or kw in lower_name for kw in ['firewall', '防火墙']):
            device_type = 'firewall'
    elif sys_oid.startswith('1.3.6.1.4.1.2011') or 'huawei' in lower_desc or '华为' in lower_desc:
        brand = 'Huawei'
        full_match = re.search(r'\b([A-Z]{1,2}\d{3,4}[A-Za-z0-9\-_/.]*)', sys_descr)
        if full_match:
            model = full_match.group(1)
        else:
            for line in sys_descr.splitlines():
                if any(kw in line.lower() for kw in ['platform software', 'version', 'copyright']):
                    continue
                match = re.search(r'Huawei\s+([A-Za-z0-9\-_/.]+)', line, re.IGNORECASE)
                if match and re.search(r'\d', match.group(1)):
                    model = match.group(1)
                    break
        if any(kw in lower_desc or kw in lower_name for kw in ['switch', '交换机', 's57', 'ce68']):
            device_type = 'switch'
        elif any(kw in lower_desc or kw in lower_name for kw in ['router', '路由', 'ar', 'ne']):
            device_type = 'router'
        elif any(kw in lower_desc or kw in lower_name for kw in ['firewall', '防火墙', 'usg']):
            device_type = 'firewall'
    elif sys_oid.startswith('1.3.6.1.4.1.9') or 'cisco' in lower_desc:
        brand = 'Cisco'
        for line in sys_descr.splitlines():
            match = re.search(r'Cisco\s+([A-Za-z0-9\-_/.]+)', line, re.IGNORECASE)
            if match:
                model = match.group(1)
                break
        if not model:
            for pat in [r'\b(Catalyst\s+\d+[A-Za-z0-9\-_.]*)', r'\b(ISR\d+[A-Za-z0-9\-_.]*)']:
                match = re.search(pat, sys_descr, re.IGNORECASE)
                if match:
                    model = match.group(1)
                    break
        if 'switch' in lower_desc or 'catalyst' in lower_desc:
            device_type = 'switch'
        elif 'router' in lower_desc or 'isr' in lower_desc:
            device_type = 'router'
    # P0-2: sysObjectID 企业前缀识别兜底 —— 原逻辑只覆盖 H3C/Huawei/Cisco，
    # 这里为 Ruijie/ZTE/Juniper/Aruba/Fortinet/F5/Dell/Arista/D-Link 等补齐 brand，
    # 并对仍为 unknown 的 device_type 做常见关键词判别。
    if oid_brand and not is_infra_agent(oid_brand):
        if not brand:
            brand = oid_brand
        if device_type == 'unknown':
            if re.search(r'switch|交换机|\bs\d{4}|ex\d{4}|ex\d{3}|jetstream|switchos', lower_desc):
                device_type = 'switch'
            elif re.search(r'firewall|防火墙|fortigate|\busg\b|pan-os', lower_desc):
                device_type = 'firewall'
            elif re.search(r'router|路由\b|\bmx\d|\bisr\b|routeros', lower_desc):
                device_type = 'router'

    if device_type == 'unknown' and any(kw in lower_desc for kw in ['linux', 'windows', 'server', 'ubuntu', 'centos']):
        device_type = 'server'
        # P0-2: 代理类 sysObjectID（VMware ESXi / Windows）可给出更准确的 brand
        brand = oid_brand if oid_brand in ('VMware', 'Microsoft') else 'Generic'
        model = 'Server'
    elif device_type == 'unknown' and oid_brand in ('net-snmp', 'VMware', 'Microsoft'):
        # sysObjectID 指向 SNMP agent（net-snmp/ESXi）但 sysDescr 无主机关键词：按服务器处理
        device_type = 'server'
        brand = oid_brand if oid_brand in ('VMware', 'Microsoft') else 'Generic'
        model = 'Server'

    # 末轮兜底：识别无线 AP（关键词/型号命中且尚未明确归类则归为 ap）
    _AP_KW = ('access point', 'access-point', 'fitap', 'fit ap', 'thin ap',
              '瘦ap', '瘦 ap', 'wireless', 'wlan', 'aruba', 'airport')
    if device_type != 'ap' and (
        any(kw in lower_desc or kw in lower_name for kw in _AP_KW)
        or re.search(r'\b(wa|ap|eap|air)\d{3,4}', lower_desc + ' ' + lower_name)
    ):
        device_type = 'ap'
    # AP 品牌推断（依据 sysObjectID 已知厂商树）
    if device_type == 'ap' and not brand:
        if sys_oid.startswith('1.3.6.1.4.1.25506'):
            brand = 'H3C'
        elif sys_oid.startswith('1.3.6.1.4.1.2011'):
            brand = 'Huawei'
        elif sys_oid.startswith('1.3.6.1.4.1.9'):
            brand = 'Cisco'
        elif sys_oid.startswith('1.3.6.1.4.1.14823'):
            brand = 'Aruba'
    # P0-4: 型号反推设备类型 —— sysDescr 常不含类型关键词（如 H3C S7506E 仅回
    # "H3C Comware Platform Software..."），但型号本身强类型化，据此兜底判型。
    if device_type in ('unknown', 'other', '', None) and model:
        mt = infer_from_model(model, brand or oid_brand)
        if mt:
            device_type = mt['device_type']
            if mt['is_wireless_controller'] and not brand:
                brand = brand or ''
    if model:
        version_match = re.search(r'(.+?)\s+(?:Ver|Version|Release|Software|V|R)\s*\d+', model, re.IGNORECASE)
        if version_match:
            model = version_match.group(1).strip()
        model = model.rstrip('.,-_ ')
    return device_type, brand, model


def update_device_snmp_info(device: Device, snmp_community='public', snmp_version='2c'):
    """通过 SNMP 更新设备的 device_type, brand, model 等字段"""
    target_ip = device.management_ip or device.ip_address
    if not target_ip:
        return False
    success, info = snmp_get_device_info(target_ip, snmp_community, snmp_version, timeout=3, retries=2)
    if not success:
        return False
    device_type, brand, model = infer_device_type_from_snmp(
        sys_descr=info.get('sys_descr', ''),
        sys_object_id=info.get('sys_object_id', ''),
        sys_name=info.get('sys_name', '')
    )
    # 本轮推断不出类型时保留库内已有类型，避免把人工修正值冲成 unknown
    if device_type in (None, '', 'unknown') and (device.device_type or '') not in ('', 'unknown'):
        device_type = device.device_type
    device.device_type = device_type or 'unknown'
    device.brand = brand or ''
    device.model = model or ''
    # 型号命中无线控制器（H3C WX / Huawei AC / Cisco WLC）→ 置无线控制器标记
    mt = infer_from_model(model, brand)
    if mt and mt['is_wireless_controller']:
        device.is_wireless_controller = True
    device.os_version = (info.get('sys_descr', '') or '')[:128]
    device.last_scanned = datetime.utcnow()
    device.updated_at = datetime.utcnow()
    try:
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        return False


def snmp_discover_interfaces_real(ip, community, version='2c', port=161):
    """Discover interface metadata through SnmpClient without net-snmp binaries."""
    client = SnmpClient(ip, community=community, version=version, port=port)
    interfaces = {}

    def ensure(if_index):
        if if_index not in interfaces:
            interfaces[if_index] = {'ifIndex': if_index}
        return interfaces[if_index]

    # ifName is preferred on modern network devices; ifDescr is the fallback.
    ifname_items = client.walk('1.3.6.1.2.1.31.1.1.1.1')
    ifdescr_items = client.walk('1.3.6.1.2.1.2.2.1.2') if not ifname_items else []
    for oid_str, value in (ifname_items or ifdescr_items):
        try:
            if_index = int(oid_str.split('.')[-1])
        except (ValueError, IndexError):
            continue
        name = _decode_hex_value(value)
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1]
        ensure(if_index)['ifDescr'] = name.strip()

    for oid_str, value in client.walk('1.3.6.1.2.1.2.2.1.3'):
        try:
            if_index = int(oid_str.split('.')[-1])
            ensure(if_index)['ifType'] = int(value)
        except (ValueError, TypeError, IndexError):
            continue

    for oid_str, value in client.walk('1.3.6.1.2.1.2.2.1.5'):
        try:
            if_index = int(oid_str.split('.')[-1])
            ensure(if_index)['ifSpeed'] = int(value)
        except (ValueError, TypeError, IndexError):
            continue

    for oid_str, value in client.walk('1.3.6.1.2.1.2.2.1.6'):
        try:
            if_index = int(oid_str.split('.')[-1])
            ensure(if_index)['mac_address'] = normalize_mac(value)
        except (ValueError, IndexError):
            continue

    for oid_str, value in client.walk('1.3.6.1.2.1.2.2.1.7'):
        try:
            if_index = int(oid_str.split('.')[-1])
            admin_val = int(value)
            ensure(if_index).update({
                'ifAdminStatus': admin_val,
                'ifAdminStatusText': 'up' if admin_val == 1 else ('down' if admin_val == 2 else 'unknown')
            })
        except (ValueError, TypeError, IndexError):
            continue

    for oid_str, value in client.walk('1.3.6.1.2.1.2.2.1.8'):
        try:
            if_index = int(oid_str.split('.')[-1])
            oper_val = int(value)
            ensure(if_index).update({
                'ifOperStatus': oper_val,
                'ifOperStatusText': 'up' if oper_val == 1 else ('down' if oper_val == 2 else 'unknown')
            })
        except (ValueError, TypeError, IndexError):
            continue

    return [interfaces[k] for k in sorted(interfaces)]
def save_discovered_interfaces(device_id, discovered):
    """Save discovered interfaces, matching by ifindex first and name second."""
    saved = []
    for intf in discovered:
        name = (intf.get('ifDescr') or intf.get('ifName') or '').strip()
        ifindex = intf.get('ifIndex')
        if not name and not ifindex:
            continue
        existing = None
        if ifindex:
            existing = Interface.query.filter_by(device_id=device_id, ifindex=ifindex).first()
        if existing is None and name:
            existing = Interface.query.filter_by(device_id=device_id, name=name).first()
        if existing is None:
            existing = Interface(device_id=device_id, name=name, ifindex=ifindex)
            db.session.add(existing)
        else:
            if name and not existing.name:
                existing.name = name
            if ifindex:
                existing.ifindex = ifindex
        existing.speed = intf.get('ifSpeed') or existing.speed
        existing.admin_status = intf.get('ifAdminStatusText') or existing.admin_status
        existing.oper_status = intf.get('ifOperStatusText') or existing.oper_status
        existing.type = intf.get('ifType') or existing.type
        existing.mac_address = normalize_mac(intf.get('mac_address')) or existing.mac_address
        existing.description = intf.get('description') or existing.description or "Auto-discovered via SNMP"
        existing.updated_at = datetime.utcnow()
        saved.append({'name': name, 'ifindex': ifindex, 'id': existing.id})
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return saved

def normalize_mac(value):
    """Normalize MAC/hex strings to lowercase colon format or return empty string."""
    if value is None:
        return ''
    if isinstance(value, bytes):
        try:
            value = value.decode('utf-8', errors='ignore')
        except Exception:
            value = str(value)
    text = str(value).strip()
    text = text.replace('-', ':').replace(' ', ':')
    if ':' in text:
        parts = text.split(':')
        if len(parts) == 6 and all(re.fullmatch(r'[0-9a-fA-F]{1,2}', p or '') for p in parts):
            return ':'.join(p.zfill(2).lower() for p in parts)
    clean = re.sub(r'[^0-9a-fA-F]', '', text)
    if len(clean) == 12:
        return ':'.join(clean[i:i+2] for i in range(0, 12, 2)).lower()
    return ''


def normalize_device_name(name):
    """Return a comparison-friendly device name."""
    value = _decode_hex_value(str(name or '').strip())
    while len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1].strip()
    return re.sub(r'\s+', ' ', value).strip().lower()


def build_discovery_candidate(info):
    """Convert raw SNMP system info into a candidate dict used for asset matching."""
    sys_name = clean_snmp_device_name(info.get('sys_name', ''), info.get('ip', ''))
    candidate = {
        'ip': (info.get('ip') or info.get('management_ip') or '').strip(),
        'name': sys_name,
        'sys_name': sys_name,
        'sys_descr': str(info.get('sys_descr') or '').strip(),
        'sys_object_id': str(info.get('sys_object_id') or '').strip(),
        'sys_location': str(info.get('sys_location') or '').strip(),
        'serial_number': str(info.get('serial_number') or '').strip() or None,
        'mac_address': normalize_mac(info.get('mac_address') or info.get('sys_mac')),
        'device_type': info.get('device_type') or 'unknown',
        'manufacturer': info.get('manufacturer') or info.get('brand') or '',
        'model': info.get('model') or '',
    }
    return candidate


def match_device_candidate(candidate):
    """Score a discovery candidate against existing devices and return a decision."""
    score = 0
    reasons = []
    match_device = None
    serial = (candidate.get('serial_number') or '').strip()
    mgmt_ip = (candidate.get('ip') or '').strip()
    mac = normalize_mac(candidate.get('mac_address'))
    name = normalize_device_name(candidate.get('name') or candidate.get('sys_name') or '')

    if serial:
        device = Device.query.filter_by(serial_number=serial).first()
        if device:
            match_device = device
            score += 50
            reasons.append('serial_number')
    if mgmt_ip and not match_device:
        device = Device.query.filter_by(management_ip=mgmt_ip).first()
        if device:
            match_device = device
            score += 40
            reasons.append('management_ip')
    if mac and not match_device:
        devices = Device.query.filter(Device.mac_address.isnot(None)).all()
        for device in devices:
            if normalize_mac(device.mac_address) == mac:
                match_device = device
                score += 25
                reasons.append('mac_address')
                break
    if name and not match_device:
        devices = Device.query.filter(Device.name.isnot(None)).all()
        for device in devices:
            if normalize_device_name(device.name) == name:
                match_device = device
                score += 15
                reasons.append('name')
                break

    if score >= 35:
        decision = 'update'
    elif score >= 20:
        decision = 'review'
    else:
        decision = 'create'

    return {
        'score': score,
        'decision': decision,
        'device_id': match_device.id if match_device else None,
        'device': match_device,
        'reasons': reasons,
    }


def discover_lldp_neighbors(ip, community='public', version='2c'):
    """Return normalized LLDP neighbor records using the pure Python SnmpClient."""
    client = SnmpClient(ip, community=community, version=version)
    ifname_map = walk_interfaces(ip, community)
    records = []
    by_index = {}
    for oid_str, chassis_id in client.walk('1.0.8802.1.1.2.1.4.1.1.5'):
        suffix = oid_str.split('1.0.8802.1.1.2.1.4.1.1.5.', 1)[-1].split('.')
        try:
            ifindex = int(suffix[-2])
            remote_index = int(suffix[-1])
        except (ValueError, IndexError):
            continue
        key = (ifindex, remote_index)
        by_index[key] = {'ifindex': ifindex, 'remote_index': remote_index, 'chassis_id': chassis_id}
    for oid_str, value in client.walk('1.0.8802.1.1.2.1.4.1.1.7'):
        suffix = oid_str.split('1.0.8802.1.1.2.1.4.1.1.7.', 1)[-1].split('.')
        try:
            key = (int(suffix[-2]), int(suffix[-1]))
        except (ValueError, IndexError):
            continue
        if key in by_index:
            by_index[key]['remote_port_id'] = value
    for oid_str, value in client.walk('1.0.8802.1.1.2.1.4.1.1.9'):
        suffix = oid_str.split('1.0.8802.1.1.2.1.4.1.1.9.', 1)[-1].split('.')
        try:
            key = (int(suffix[-2]), int(suffix[-1]))
        except (ValueError, IndexError):
            continue
        if key in by_index:
            by_index[key]['remote_system_name'] = value
    for oid_str, value in client.walk('1.0.8802.1.1.2.1.4.1.1.10'):
        suffix = oid_str.split('1.0.8802.1.1.2.1.4.1.1.10.', 1)[-1].split('.')
        try:
            key = (int(suffix[-2]), int(suffix[-1]))
        except (ValueError, IndexError):
            continue
        if key in by_index:
            by_index[key]['remote_sys_desc'] = value
    for key, item in by_index.items():
        item['local_port'] = ifname_map.get(item['ifindex'], '')
        item['protocol'] = 'LLDP'
        item['confidence'] = 100
        records.append(item)
    return records


def discover_cdp_neighbors(ip, community='public', version='2c'):
    """Return normalized Cisco CDP neighbor records."""
    client = SnmpClient(ip, community=community, version=version)
    ifname_map = walk_interfaces(ip, community)
    records = []
    device_id_map = {}
    port_id_map = {}
    for oid_str, value in client.walk('1.3.6.1.4.1.9.9.23.1.2.1.1.6'):
        try:
            ifindex = int(oid_str.split('.')[-1])
            device_id_map[ifindex] = value
        except (ValueError, IndexError):
            continue
    for oid_str, value in client.walk('1.3.6.1.4.1.9.9.23.1.2.1.1.7'):
        try:
            ifindex = int(oid_str.split('.')[-1])
            port_id_map[ifindex] = value
        except (ValueError, IndexError):
            continue
    for ifindex, remote_device in device_id_map.items():
        records.append({
            'ifindex': ifindex,
            'local_port': ifname_map.get(ifindex, ''),
            'remote_device_id': remote_device,
            'chassis_id': remote_device,
            'remote_system_name': remote_device,
            'remote_port_id': port_id_map.get(ifindex, ''),
            'protocol': 'CDP',
            'confidence': 100,
        })
    return records


def discover_arp_table(ip, community='public', version='2c'):
    """Return raw ARP/IP-MAC records from a network device."""
    client = SnmpClient(ip, community=community, version=version)
    records = []
    phys = client.walk('1.3.6.1.2.1.4.22.1.2')
    for oid_str, mac in phys:
        parts = oid_str.split('.')
        try:
            ifindex = int(parts[-5])
            ip = '.'.join(parts[-4:])
            records.append({'ifindex': ifindex, 'ip': ip, 'mac': normalize_mac(mac), 'protocol': 'ARP'})
        except (ValueError, IndexError):
            continue
    return records


def discover_topology_summary(ip, community='public', version='2c'):
    """Run LLDP/CDP/ARP/FDB discovery for one device and return a normalized summary."""
    return {
        'ip': ip,
        'lldp': discover_lldp_neighbors(ip, community, version),
        'cdp': discover_cdp_neighbors(ip, community, version),
        'arp': discover_arp_table(ip, community, version),
        'fdb': discover_fdb_table(ip, community, version),
    }

def discover_fdb_table(ip, community='public', version='2c'):
    """Return raw FDB MAC/port records from dot1qTpFdbTable."""
    client = SnmpClient(ip, community=community, version=version)
    records = []
    for oid_str, port in client.walk('1.3.6.1.2.1.17.7.1.2.2.1.2'):
        records.append({'oid': oid_str, 'port': port, 'protocol': 'FDB'})
    return records

# ---------- 厂商 OID 映射 ----------
OID_MAPPINGS = {
    'linux': {
        'cpu_usage': ['1.3.6.1.4.1.2021.11.9.0', '1.3.6.1.4.1.2021.11.10.0', '1.3.6.1.4.1.2021.11.11.0'],
        'memory_usage': ['1.3.6.1.4.1.2021.4.6.0', '1.3.6.1.4.1.2021.4.5.0'],
        'disk_usage': ['1.3.6.1.4.1.2021.9.1.9.1', '1.3.6.1.4.1.2021.9.1.8.1'],
        'temperature': [], 'power_consumption': [], 'power_supply': [],
    },
    'cisco': {
        'cpu_usage': ['1.3.6.1.4.1.9.9.109.1.1.1.1.3.1', '1.3.6.1.4.1.9.9.109.1.1.1.1.4.1'],
        'memory_usage': ['1.3.6.1.4.1.9.9.48.1.1.1.5.1', '1.3.6.1.4.1.9.9.48.1.1.1.6.1', '1.3.6.1.4.1.9.9.48.1.1.1.4.1'],
        'disk_usage': ['1.3.6.1.4.1.9.9.10.1.1.4.1.4.1', '1.3.6.1.4.1.9.9.10.1.1.4.1.5.1'],
        'temperature': ['1.3.6.1.4.1.9.9.13.1.3.1.3.1'],
        'power_supply': ['1.3.6.1.4.1.9.9.13.1.4.1.3.1'],
        'power_consumption': [],
    },
    'huawei': {
        'cpu_usage': ['1.3.6.1.4.1.2011.6.3.4.1.2.1.3.1', '1.3.6.1.4.1.2011.6.3.4.1.2.1.4.1'],
        'memory_usage': ['1.3.6.1.4.1.2011.6.3.5.1.1.2.1.6.1', '1.3.6.1.4.1.2011.6.3.5.1.1.2.1.7.1', '1.3.6.1.4.1.2011.6.3.5.1.1.2.1.8.1'],
        'temperature': ['1.3.6.1.4.1.2011.6.3.8.1.2.1.3.1'],
        'power_supply': ['1.3.6.1.4.1.2011.6.3.9.1.1.3.1.4.1'],
        'disk_usage': [], 'power_consumption': [],
    },
    'h3c': {
        'cpu_usage': ['1.3.6.1.4.1.25506.2.6.1.1.1.1.6.1', '1.3.6.1.4.1.25506.2.13.1.1.2.1.8.1'],
        'memory_usage': ['1.3.6.1.4.1.25506.2.6.1.1.1.1.8.1'],
        'temperature': ['1.3.6.1.4.1.25506.2.6.1.1.1.1.12.1'],
        'power_supply': ['1.3.6.1.4.1.25506.2.6.1.1.1.1.20.1'],
        'disk_usage': [], 'power_consumption': [],
    },
    'ruijie': {
        'cpu_usage': ['1.3.6.1.4.1.4881.1.1.10.2.10.1.1.1.2.1'],
        'memory_usage': ['1.3.6.1.4.1.4881.1.1.10.2.10.1.1.1.4.1'],
        'temperature': ['1.3.6.1.4.1.4881.1.1.10.2.10.1.1.1.6.1'],
        'power_supply': ['1.3.6.1.4.1.4881.1.1.10.2.10.1.1.1.8.1'],
        'disk_usage': [], 'power_consumption': [],
    },
}
FALLBACK_OIDS = {
    'cpu_usage': ['1.3.6.1.2.1.25.3.3.1.2.1'],
    'memory_usage': ['1.3.6.1.2.1.25.2.3.1.5.1', '1.3.6.1.2.1.25.2.3.1.6.1'],
    'disk_usage': ['1.3.6.1.2.1.25.2.3.1.5.2'],
    'temperature': [], 'power_consumption': [], 'power_supply': [],
}


def get_device_snmp_data(device, timeout=None):
    """采集设备的 CPU、内存、磁盘、温度、电源等数据"""
    ip = device.management_ip
    community = getattr(device, 'snmp_community', 'public')
    version = str(getattr(device, 'snmp_version', '2c'))

    vendor = getattr(device, 'vendor', '').lower()
    if not vendor and device.device_type:
        dt = device.device_type.lower()
        if 'h3c' in dt or 'hp' in dt: vendor = 'h3c'
        elif 'cisco' in dt: vendor = 'cisco'
        elif 'huawei' in dt: vendor = 'huawei'
        elif 'linux' in dt: vendor = 'linux'
        elif 'ruijie' in dt: vendor = 'ruijie'

    vendor_oids = OID_MAPPINGS.get(vendor, {})

    def try_oids(metric):
        for oid in vendor_oids.get(metric, []):
            val = snmp_get(ip, community, version, oid, timeout=timeout)
            if val is not None: return val
        for oid in FALLBACK_OIDS.get(metric, []):
            val = snmp_get(ip, community, version, oid, timeout=timeout)
            if val is not None: return val
        return None

    def to_float(v):
        try: return float(v) if v is not None else None
        except (ValueError, TypeError): return None

    result = {k: None for k in ['cpu_usage', 'memory_usage', 'disk_usage', 'temperature', 'power_consumption', 'power_supply']}

    cpu = try_oids('cpu_usage')
    result['cpu_usage'] = to_float(cpu)

    mem = try_oids('memory_usage')
    if mem is not None:
        if vendor == 'linux':
            total = snmp_get(ip, community, version, '1.3.6.1.4.1.2021.4.5.0', timeout)
            if total:
                tf, mf = to_float(total), to_float(mem)
                if tf and mf is not None:
                    result['memory_usage'] = ((tf - mf) / tf) * 100
        elif vendor == 'cisco':
            total = snmp_get(ip, community, version, '1.3.6.1.4.1.9.9.48.1.1.1.4.1', timeout)
            if total:
                tf, mf = to_float(total), to_float(mem)
                if tf and mf is not None:
                    result['memory_usage'] = (mf / tf) * 100
        else:
            result['memory_usage'] = to_float(mem)

    disk = try_oids('disk_usage')
    if disk is not None:
        if vendor == 'linux':
            total = snmp_get(ip, community, version, '1.3.6.1.4.1.2021.9.1.8.1', timeout)
            if total:
                tf, df = to_float(total), to_float(disk)
                if tf and df is not None:
                    result['disk_usage'] = (df / tf) * 100
        elif vendor == 'cisco':
            total = snmp_get(ip, community, version, '1.3.6.1.4.1.9.9.10.1.1.4.1.4.1', timeout)
            if total:
                tf, df = to_float(total), to_float(disk)
                if tf and df is not None:
                    result['disk_usage'] = ((tf - df) / tf) * 100
        else:
            result['disk_usage'] = to_float(disk)

    temp = try_oids('temperature')
    result['temperature'] = to_float(temp)
    power = try_oids('power_consumption')
    result['power_consumption'] = to_float(power)

    ps = try_oids('power_supply')
    if ps is not None:
        pf = to_float(ps)
        if pf == 1: result['power_supply'] = '正常'
        elif pf == 2: result['power_supply'] = '故障'
        else: result['power_supply'] = str(ps)

    return result


def snmp_detect_trunk_ports(ip, community='public', version='2c', timeout=3):
    """
    通过 SNMP 检测设备的 trunk 端口。
    返回: {port_name: True} 表示该端口为 trunk 模式。
    支持多厂商 OID：
      - Cisco: CISCO-VTP-MIB::vlanTrunkPortDynamicStatus (1.3.6.1.4.1.9.9.46.1.6.1.1.14)
               值 1 = trunking, 2 = notTrunking
      - H3C/Huawei: HH3C-L2DEV-MIB::hh3cPortLayerStatus / IEEE8021-PAE-MIB
               使用 1.3.6.1.2.1.17.7.1.2.2.1.2 (dot1qVlanCurrentEgressPorts) 推断
      - 通用: 查询 ifType (1.3.6.1.2.1.2.2.1.3) 中值为 135 (l2vlan) / 53 (propVirtual)
              以及 dot1qPortAcceptableFrameTypes (1.3.6.1.2.1.17.7.1.4.5.1.3)
              值 1 = admitAll, 2 = admitOnlyVlanTagged (trunk)
    """
    trunk_ports = {}

    # --- 方式 1: 通用 IEEE 802.1Q 查询 (dot1qPortAcceptableFrameTypes) ---
    # OID: 1.3.6.1.2.1.17.7.1.4.5.1.3.<port>  值=2 表示只接受 tagged 帧 → trunk
    try:
        results = snmp_walk(ip, '1.3.6.1.2.1.17.7.1.4.5.1.3', community, version, timeout)
        if results:
            # 需要将 dot1q 端口号映射到 ifIndex → ifName
            # dot1dBasePortIfIndex: 1.3.6.1.2.1.17.1.4.3.1.2.<port> = ifIndex
            port_ifindex_map = {}
            baseport_results = snmp_walk(ip, '1.3.6.1.2.1.17.1.4.3.1.2', community, version, timeout)
            for oid_str, val in baseport_results:
                # oid_str 形如 1.3.6.1.2.1.17.1.4.3.1.2.<port>
                port_num = int(oid_str.split('.')[-1])
                port_ifindex_map[port_num] = int(val)

            # 获取 ifIndex → ifName 映射
            ifname_map = walk_interfaces(ip, community, timeout)

            for oid_str, val in results:
                port_num = int(oid_str.split('.')[-1])
                try:
                    frame_type = int(val)
                except (ValueError, TypeError):
                    continue
                if frame_type == 2:  # admitOnlyVlanTagged → trunk
                    ifindex = port_ifindex_map.get(port_num)
                    if ifindex and ifindex in ifname_map:
                        trunk_ports[ifname_map[ifindex]] = True
    except Exception as e:
        logger.debug(f"dot1q trunk 检测失败 {ip}: {e}")

    # --- 方式 2: Cisco 专用 VTP MIB ---
    if not trunk_ports:
        try:
            # vlanTrunkPortDynamicStatus: 1.3.6.1.4.1.9.9.46.1.6.1.1.14.<ifIndex>
            # 值 1 = trunking
            results = snmp_walk(ip, '1.3.6.1.4.1.9.9.46.1.6.1.1.14', community, version, timeout)
            if results:
                ifname_map = walk_interfaces(ip, community, timeout)
                for oid_str, val in results:
                    # oid_str 形如 1.3.6.1.4.1.9.9.46.1.6.1.1.14.<ifIndex>
                    ifindex = int(oid_str.split('.')[-1])
                    try:
                        status_val = int(val)
                    except (ValueError, TypeError):
                        continue
                    if status_val == 1:  # trunking
                        port_name = ifname_map.get(ifindex)
                        if port_name:
                            trunk_ports[port_name] = True
        except Exception as e:
            logger.debug(f"Cisco VTP trunk 检测失败 {ip}: {e}")

    # --- 方式 3: H3C 专用 ---
    if not trunk_ports:
        try:
            # HH3C-PORT-SEC-MIB / hh3cPortMode 用 1.3.6.1.4.1.25506.2.53.1.1.1.1.2
            # 值 1 = access, 2 = trunk, 3 = hybrid
            results = snmp_walk(ip, '1.3.6.1.4.1.25506.2.53.1.1.1.1.2', community, version, timeout)
            if results:
                ifname_map = walk_interfaces(ip, community, timeout)
                # 这个 OID 的索引可能直接是 ifIndex
                for oid_str, val in results:
                    ifindex = int(oid_str.split('.')[-1])
                    try:
                        mode_val = int(val)
                    except (ValueError, TypeError):
                        continue
                    if mode_val in (2, 3):  # trunk or hybrid
                        port_name = ifname_map.get(ifindex)
                        if port_name:
                            trunk_ports[port_name] = True
        except Exception as e:
            logger.debug(f"H3C trunk 检测失败 {ip}: {e}")

    if trunk_ports:
        logger.info(f"SNMP trunk 端口检测 {ip}: 发现 {len(trunk_ports)} 个 trunk 端口: {list(trunk_ports.keys())}")
    return trunk_ports


def snmp_get_with_timeout(ip, community, version, oid, timeout=SNMP_TIMEOUT):
    """兼容旧接口，直接调用 snmp_get"""
    return snmp_get(ip, community, version, oid, timeout)
