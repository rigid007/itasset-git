# snmp_utils.py
"""SNMP utility functions: get, walk, device info, interface discovery."""
import subprocess
import shutil
import re
import time
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from extensions import db
from models import Device, Interface

logger = logging.getLogger(__name__)

SNMP_TIMEOUT = 3


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
    """通过系统 snmpget 命令执行 SNMP GET 返回: 值 (int/float/str) 或 None"""
    if community is None:
        community = 'public'

    snmpget_cmd = shutil.which('snmpget')
    if not snmpget_cmd:
        logger.error("snmpget 命令不存在，请安装 net-snmp 工具")
        return None

    ver = '2c' if version == '2c' else '1'
    cmd = [snmpget_cmd, '-v', ver, '-c', str(community), '-t', str(timeout),
           '-r', '1', '-O', 'qv', str(ip), str(oid)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        if result.returncode != 0:
            logger.warning(f"snmpget {ip} {oid} 失败 (code {result.returncode}): {result.stderr.strip()}")
            return None
        output = result.stdout.strip()
        if not output:
            return None
        # hex格式解码（含中文的OCTET STRING输出为hex）
        output = _decode_hex_value(output)
        # 去除两端的引号（某些SNMP代理返回带引号的值）
        if output.startswith('"') and output.endswith('"'):
            output = output[1:-1].strip()
        try:
            return int(output)
        except ValueError:
            try:
                return float(output)
            except ValueError:
                return output
    except subprocess.TimeoutExpired:
        logger.warning(f"snmpget {ip} {oid} 超时")
        return None
    except Exception as e:
        logger.error(f"snmpget {ip} {oid} 异常: {e}")
        return None


def snmp_walk(ip: str, oid: str, community: str = 'public',
              version: str = '2c', timeout: int = 5,
              retries: int = 2, total_timeout: Optional[int] = None,
              on_line=None, raise_on_error: bool = False) -> List[Tuple[str, str]]:
    """通过系统 snmpwalk 执行 SNMP WALK，返回 [(oid, value), ...]。

    新增参数：
      total_timeout   : 整体超时（秒）。默认 max(60, timeout*(retries+1)*5)。
                        某些厂商（如 H3C WLAN 表）单条处理极慢、整表 walk 可能需数分钟，
                        调用方（如 AC 异步发现）应传入较大的值以免被提前掐断。
      on_line        : 可选回调 on_line(oid_str, value_str)，每解析出一行即调用，
                        用于长 walk 的实时进度上报（逐行流式读取）。
      raise_on_error : True 时，命令不存在/超时/进程非零退出会抛 SNMPWalkError，
                        而非静默返回 []，便于上层把真实原因显示给用户。
                        （“OID 不存在返回空列表”仍属正常结果，不会抛异常。）
    """
    snmpwalk_cmd = shutil.which('snmpwalk')
    if not snmpwalk_cmd:
        logger.error("snmpwalk 命令不存在，请安装 net-snmp 工具")
        return []

    oid = oid.lstrip('.')
    ver = '2c' if version == '2c' else '1'
    cmd = [snmpwalk_cmd, '-v', ver, '-c', str(community), '-t', str(timeout),
           '-r', str(retries), '-Cc', '-On', str(ip), oid]

    oid = oid.lstrip('.')
    ver = '2c' if version == '2c' else '1'
    cmd = [snmpwalk_cmd, '-v', ver, '-c', str(community), '-t', str(timeout),
           '-r', str(retries), '-Cc', '-On', str(ip), oid]
    base_oid = '.' + oid if not oid.startswith('.') else oid
    tt = total_timeout if total_timeout else max(60, timeout * (retries + 1) * 5)
    results: List[Tuple[str, str]] = []

    # 流式模式：逐行读取，支持 on_line 实时回调与超长 total_timeout
    if on_line is not None:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, bufsize=1)
        except Exception as e:
            logger.error(f"snmpwalk 启动失败 {ip} {oid}: {e}")
            if raise_on_error:
                raise SNMPWalkError(str(e))
            return []
        start = time.time()
        timed_out = False
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if time.time() - start > tt:
                    timed_out = True
                    break
                parsed = _parse_walk_line(line, base_oid)
                if parsed:
                    results.append(parsed)
                    on_line(*parsed)
            proc.stdout.close()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            raise
        if timed_out:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            err = f"SNMP WALK 超时（>{tt}秒，已读取 {len(results)} 行）"
            logger.warning(f"snmpwalk {ip} {oid} (community={community!r}) {err}")
            if raise_on_error:
                raise SNMPWalkError(err)
            return results
        if proc.returncode != 0 and not results:
            stderr = proc.stderr.read() if proc.stderr else ''
            err = f"snmpwalk 失败 (code {proc.returncode}): {stderr.strip()}"
            logger.warning(f"snmpwalk {ip} {oid} (community={community!r}) {err}")
            if raise_on_error:
                raise SNMPWalkError(err)
        return results

    # 缓冲模式（默认）：一次性收集输出后解析
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=tt)
        if result.returncode != 0 and not result.stdout.strip():
            err = f"snmpwalk 失败 (code {result.returncode}): {result.stderr.strip()}"
            logger.warning(f"snmpwalk {ip} {oid} (community={community!r}) {err}")
            if raise_on_error:
                raise SNMPWalkError(err)
            return []
        for line in result.stdout.splitlines():
            parsed = _parse_walk_line(line, base_oid)
            if parsed:
                results.append(parsed)
        return results
    except subprocess.TimeoutExpired:
        err = f"SNMP WALK 超时（>{tt}秒）"
        logger.warning(f"snmpwalk {ip} {oid} {err}")
        if raise_on_error:
            raise SNMPWalkError(err)
        return []
    except SNMPWalkError:
        raise
    except Exception as e:
        logger.error(f"snmpwalk {ip} {oid} 异常: {e}")
        if raise_on_error:
            raise SNMPWalkError(str(e))
        return []


def walk_interfaces(ip, community='public', timeout=5):
    """通过 snmpwalk 获取接口名称列表，返回 {ifIndex: ifName}"""
    result = {}
    oid = '1.3.6.1.2.1.31.1.1.1.1'
    snmpwalk_cmd = shutil.which('snmpwalk')
    if not snmpwalk_cmd:
        logger.error("snmpwalk 命令不存在，请安装 net-snmp 工具")
        return result
    cmd = [snmpwalk_cmd, '-v', '2c', '-c', community, '-t', str(timeout),
           '-r', '1', '-O', 'v', ip, oid]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+2, check=False)
        if proc.returncode != 0:
            logger.warning(f"snmpwalk {ip} {oid} 失败: {proc.stderr.strip()}")
            return result
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or '=' not in line:
                continue
            left, right = line.split('=', 1)
            oid_part = left.strip()
            match = re.search(r'\.(\d+)$', oid_part)
            if not match:
                continue
            ifindex = int(match.group(1))
            value = right.strip()
            if value.startswith('STRING: '):
                value = value[8:]
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            result[ifindex] = value
        return result
    except subprocess.TimeoutExpired:
        logger.warning(f"snmpwalk {ip} {oid} 超时")
        return result
    except Exception as e:
        logger.error(f"snmpwalk {ip} {oid} 异常: {e}")
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
                status='unknown')
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
        return {'success': True, 'device_id': device.id, 'action': action, 'message': msg, 'device': device}
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
    if device_type == 'unknown' and any(kw in lower_desc for kw in ['linux', 'windows', 'server', 'ubuntu', 'centos']):
        device_type = 'server'
        brand = 'Generic'
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
    device.device_type = device_type or 'unknown'
    device.brand = brand or ''
    device.model = model or ''
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
    """通过 SNMP 获取设备的所有接口信息 (pysnmp bulkCmd)"""
    from pysnmp.entity.rfc3413.oneliner import cmdgen
    cmd_gen = cmdgen.CommandGenerator()
    mp_model = 0 if version == '1' else 1
    oids = [
        '1.3.6.1.2.1.2.2.1.1', '1.3.6.1.2.1.2.2.1.2', '1.3.6.1.2.1.2.2.1.3',
        '1.3.6.1.2.1.2.2.1.5', '1.3.6.1.2.1.2.2.1.7', '1.3.6.1.2.1.2.2.1.8',
    ]
    errorIndication, errorStatus, errorIndex, varBindTable = cmd_gen.bulkCmd(
        cmdgen.CommunityData(community, mpModel=mp_model),
        cmdgen.UdpTransportTarget((ip, port), timeout=2, retries=2),
        0, 25, *[cmdgen.MibVariable(oid) for oid in oids], lookupMib=False
    )
    if errorIndication or errorStatus:
        logger.error(f"SNMP bulk 错误: {errorIndication or errorStatus}")
        return []
    interfaces = {}
    for varBinds in varBindTable:
        for oid, val in varBinds:
            if_index = oid[-1]
            if if_index not in interfaces:
                interfaces[if_index] = {'ifIndex': if_index}
            oid_str = '.'.join(str(x) for x in oid[:-1])
            pp = val.prettyPrint() if hasattr(val, 'prettyPrint') else str(val)
            if oid_str == '1.3.6.1.2.1.2.2.1.2':
                interfaces[if_index]['ifDescr'] = pp
            elif oid_str == '1.3.6.1.2.1.2.2.1.3':
                interfaces[if_index]['ifType'] = int(val)
            elif oid_str == '1.3.6.1.2.1.2.2.1.5':
                interfaces[if_index]['ifSpeed'] = int(val)
            elif oid_str == '1.3.6.1.2.1.2.2.1.7':
                admin_val = int(val)
                interfaces[if_index]['ifAdminStatus'] = admin_val
                interfaces[if_index]['ifAdminStatusText'] = 'up' if admin_val == 1 else ('down' if admin_val == 2 else 'unknown')
            elif oid_str == '1.3.6.1.2.1.2.2.1.8':
                oper_val = int(val)
                interfaces[if_index]['ifOperStatus'] = oper_val
                interfaces[if_index]['ifOperStatusText'] = 'up' if oper_val == 1 else ('down' if oper_val == 2 else 'unknown')
    return list(interfaces.values())


def save_discovered_interfaces(device_id, discovered):
    """将发现的接口列表保存到数据库，如已存在则更新"""
    saved = []
    for intf in discovered:
        name = intf.get('ifDescr')
        if not name:
            continue
        existing = Interface.query.filter_by(device_id=device_id, name=name).first()
        if not existing:
            new_intf = Interface(
                device_id=device_id, name=name, ifindex=intf.get('ifIndex'),
                speed=intf.get('ifSpeed'), admin_status=intf.get('ifAdminStatusText'),
                oper_status=intf.get('ifOperStatusText'), description="Auto-discovered via SNMP",
                created_at=datetime.utcnow(), updated_at=datetime.utcnow()
            )
            db.session.add(new_intf)
            saved.append({'name': name, 'ifindex': intf.get('ifIndex')})
        else:
            existing.ifindex = intf.get('ifIndex') or existing.ifindex
            existing.speed = intf.get('ifSpeed') or existing.speed
            existing.admin_status = intf.get('ifAdminStatusText') or existing.admin_status
            existing.oper_status = intf.get('ifOperStatusText') or existing.oper_status
            existing.updated_at = datetime.utcnow()
            saved.append({'name': name, 'ifindex': existing.ifindex})
    db.session.commit()
    return saved


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


def get_device_snmp_data(device):
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
            val = snmp_get(ip, community, version, oid, timeout=3)
            if val is not None: return val
        for oid in FALLBACK_OIDS.get(metric, []):
            val = snmp_get(ip, community, version, oid, timeout=3)
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
            total = snmp_get(ip, community, version, '1.3.6.1.4.1.2021.4.5.0', 3)
            if total:
                tf, mf = to_float(total), to_float(mem)
                if tf and mf is not None:
                    result['memory_usage'] = ((tf - mf) / tf) * 100
        elif vendor == 'cisco':
            total = snmp_get(ip, community, version, '1.3.6.1.4.1.9.9.48.1.1.1.4.1', 3)
            if total:
                tf, mf = to_float(total), to_float(mem)
                if tf and mf is not None:
                    result['memory_usage'] = (mf / tf) * 100
        else:
            result['memory_usage'] = to_float(mem)

    disk = try_oids('disk_usage')
    if disk is not None:
        if vendor == 'linux':
            total = snmp_get(ip, community, version, '1.3.6.1.4.1.2021.9.1.8.1', 3)
            if total:
                tf, df = to_float(total), to_float(disk)
                if tf and df is not None:
                    result['disk_usage'] = (df / tf) * 100
        elif vendor == 'cisco':
            total = snmp_get(ip, community, version, '1.3.6.1.4.1.9.9.10.1.1.4.1.4.1', 3)
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
