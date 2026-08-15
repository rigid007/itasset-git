# network_utils.py
"""Network utility functions: ping, IP validation, IP range parsing, device scanning."""
import subprocess
import socket
import platform
import select
import time
import ipaddress
import re
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from extensions import db

import logging
logger = logging.getLogger(__name__)

DEFAULT_PING_TIMEOUT = 2


def is_valid_ip(ip_str):
    """验证IP地址格式"""
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False


def is_valid_mac(mac_str):
    """验证MAC地址格式"""
    mac_pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
    return re.match(mac_pattern, mac_str) is not None


def allowed_file(filename, allowed_extensions=None):
    """检查文件扩展名是否允许"""
    if allowed_extensions is None:
        allowed_extensions = {'xlsx', 'xls', 'csv'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def ping_device(ip, timeout=2):
    """使用系统ping命令检测设备 返回: (是否成功, 响应时间ms)"""
    try:
        if platform.system().lower() == "windows":
            ping_cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), ip]
        else:
            ping_cmd = ["ping", "-c", "1", "-W", str(timeout), ip]
        result = subprocess.run(ping_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout+1)
        if result.returncode == 0:
            output = result.stdout
            time_pattern = r"time[=<](\d+\.?\d*)\s*ms"
            match = re.search(time_pattern, output, re.IGNORECASE)
            if match:
                response_time = float(match.group(1))
                return True, response_time
            return True, 0
        return False, 0
    except Exception:
        return False, 0


def ping_device_strict(ip: str, timeout: float = 2.0, retries: int = 2) -> Tuple[bool, float]:
    """严格的Ping检测，使用多种方法并重试"""
    methods = [
        ('system_ping', ping_device_system),
        ('socket_ping', ping_device_socket),
        ('tcp_ping', ping_device_tcp)
    ]
    best_response = float('inf')
    for attempt in range(retries):
        for method_name, method_func in methods:
            try:
                success, response_time = method_func(ip, timeout)
                if success and response_time > 0:
                    if response_time < best_response:
                        best_response = response_time
                    return True, best_response
            except Exception:
                continue
        if attempt < retries - 1:
            time.sleep(0.2)
    return False, 0


def ping_device_system(ip: str, timeout: float = 2.0) -> Tuple[bool, float]:
    """使用系统Ping命令"""
    try:
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
        timeout_value = str(int(timeout * 1000)) if platform.system().lower() == 'windows' else str(int(timeout))
        cmd = ['ping', param, '1', timeout_param, timeout_value, ip]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 1)
        if result.returncode == 0:
            match = re.search(r'(?:时间|time)[=<](\d+\.?\d*)', result.stdout, re.IGNORECASE)
            if match:
                return True, float(match.group(1))
            return True, 1.0
        return False, 0
    except Exception:
        return False, 0


def ping_device_socket(ip: str, timeout: float = 1.0) -> Tuple[bool, float]:
    """使用Socket连接检测（退化为TCP检测）"""
    return ping_device_tcp(ip, timeout)


def ping_device_tcp(ip: str, timeout: float = 1.0, port: int = 80) -> Tuple[bool, float]:
    """TCP端口连通性检测"""
    try:
        start_time = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        if result == 0:
            return True, (time.time() - start_time) * 1000
        return False, 0
    except Exception:
        return False, 0


def batch_ping_devices(ip_list: List[str], timeout: float = 1.0, max_workers: int = 20) -> Dict[str, dict]:
    """批量并发Ping检测"""
    results = {}
    def ping_with_timeout(ip: str):
        try:
            success, response_time = ping_device_strict(ip, timeout, retries=1)
            return {'ip': ip, 'online': success, 'response_time': response_time, 'method': 'strict_ping'}
        except Exception as e:
            return {'ip': ip, 'online': False, 'response_time': 0, 'method': 'error', 'error': str(e)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(ping_with_timeout, ip): ip for ip in ip_list}
        for future in concurrent.futures.as_completed(futures):
            ip = futures[future]
            try:
                result = future.result(timeout=timeout + 0.5)
                results[ip] = result
            except concurrent.futures.TimeoutError:
                results[ip] = {'ip': ip, 'online': False, 'response_time': 0, 'method': 'timeout'}
            except Exception as e:
                results[ip] = {'ip': ip, 'online': False, 'response_time': 0, 'method': 'error', 'error': str(e)}
    return results


def calculate_checksum(data):
    """计算ICMP校验和"""
    sum_val = 0
    count_to = (len(data) // 2) * 2
    for count in range(0, count_to, 2):
        this_val = data[count + 1] * 256 + data[count]
        sum_val = sum_val + this_val
        sum_val = sum_val & 0xffffffff
    if count_to < len(data):
        sum_val = sum_val + data[len(data) - 1]
        sum_val = sum_val & 0xffffffff
    sum_val = (sum_val >> 16) + (sum_val & 0xffff)
    sum_val = sum_val + (sum_val >> 16)
    answer = ~sum_val
    answer = answer & 0xffff
    answer = answer >> 8 | (answer << 8 & 0xff00)
    return answer


def detect_device_reliable(ip, timeout=2, use_tcp_check=False):
    """简化的设备检测，主要依赖ping"""
    for attempt in range(2):
        success, response_time = ping_device(ip, timeout=1)
        if success:
            return True, response_time, 'ping'
        if use_tcp_check:
            success, rtt = ping_device_tcp(ip, timeout=1)
            if success:
                return True, rtt, 'tcp'
        time.sleep(0.1)
    return False, 0, 'ping_failed'


def parse_ip_range(ip_range_str):
    """解析IP段字符串，返回IP地址列表"""
    ip_list = []
    if not ip_range_str:
        raise ValueError("IP段不能为空")
    ip_range_str = ip_range_str.strip()
    if '/' in ip_range_str:
        network = ipaddress.ip_network(ip_range_str, strict=False)
        for ip in network.hosts():
            ip_list.append(str(ip))
        return ip_list
    elif '-' in ip_range_str:
        parts = ip_range_str.rsplit('-', 1)
        start_ip_str = parts[0].strip()
        end_part = parts[1].strip()
        if '.' not in end_part:
            base_parts = start_ip_str.split('.')
            if len(base_parts) != 4:
                raise ValueError("起始IP格式无效")
            base_parts[-1] = end_part
            end_ip_str = '.'.join(base_parts)
        else:
            end_ip_str = end_part
        if not (is_valid_ip(start_ip_str) and is_valid_ip(end_ip_str)):
            raise ValueError("无效的IP地址")
        start = ipaddress.IPv4Address(start_ip_str)
        end = ipaddress.IPv4Address(end_ip_str)
        if start > end:
            start, end = end, start
        current = start
        while current <= end:
            ip_list.append(str(current))
            current = ipaddress.IPv4Address(int(current) + 1)
        return ip_list
    elif is_valid_ip(ip_range_str):
        return [ip_range_str]
    else:
        raise ValueError(f"无效的IP段格式: {ip_range_str}")


def scan_ip_range_worker(ip, ping_timeout, ping_count,
                         snmp_community, snmp_version,
                         snmp_timeout, snmp_retries, check_snmp_flag):
    """扫描单个IP的工作线程函数"""
    from utils.snmp_utils import snmp_get_device_info
    from models.models import Device

    result = {
        'ip': ip, 'online': False, 'ping_time': 0,
        'snmp_support': False, 'sysinfo': {}, 'existing': False
    }
    existing_device = Device.query.filter_by(management_ip=ip).first()
    if existing_device:
        result['existing'] = True
        result['device_name'] = existing_device.name
        result['existing_name'] = existing_device.name
        return result
    online, ping_time = ping_device(ip, ping_timeout)
    result['online'] = online
    if online:
        result['ping_time'] = ping_time
        if check_snmp_flag:
            success, sysinfo = snmp_get_device_info(ip, snmp_community, snmp_version, snmp_timeout, snmp_retries)
            result['snmp_support'] = success
            result['sysinfo'] = sysinfo
            if sysinfo:
                result['device_name'] = sysinfo.get('sys_name', f"设备_{ip}")
                result['description'] = sysinfo.get('sys_descr', 'SNMP设备')
        else:
            result['device_name'] = f"设备_{ip}"
            result['description'] = '通过IP扫描发现的设备'
    return result


def ip_range_import(
    ip_range_str: str,
    device_type: str = 'unknown',
    cabinet_id: Optional[int] = None,
    manufacturer: Optional[str] = None,
    auto_naming: bool = True,
    skip_existing: bool = True,
    use_ping: bool = True,
    ping_timeout: int = 2,
    concurrent: int = 10,
    strict_check: bool = True,
    verify_tcp: bool = False
) -> Dict[str, Any]:
    """批量导入IP段中的设备"""
    from models.models import Device

    results = {'total': 0, 'added': 0, 'skipped': 0, 'failed': 0,
               'online_count': 0, 'offline_count': 0, 'results': []}
    try:
        ip_list = parse_ip_range(ip_range_str)
        results['total'] = len(ip_list)
        for ip in ip_list:
            if skip_existing and Device.query.filter_by(management_ip=ip).first():
                results['skipped'] += 1
                continue
            if use_ping:
                online, rtt, method = detect_device_reliable(ip, timeout=ping_timeout, use_tcp_check=verify_tcp)
                if not online:
                    results['offline_count'] += 1
                    results['skipped'] += 1
                    continue
                results['online_count'] += 1
            dev_name = f"设备_{ip}" if auto_naming else ip
            new_dev = Device(
                name=dev_name, management_ip=ip, device_type=device_type,
                manufacturer=manufacturer, cabinet_id=cabinet_id, status='online' if use_ping else 'unknown',
                last_checked=datetime.utcnow(), last_seen=datetime.utcnow() if use_ping else None,
                ping_time=rtt if use_ping else None, created_at=datetime.utcnow(), updated_at=datetime.utcnow()
            )
            db.session.add(new_dev)
            results['added'] += 1
        db.session.commit()
        return results
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'message': str(e), **results}
