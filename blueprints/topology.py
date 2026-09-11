# blueprints/topology.py
import json
import random
import re
import socket
import threading
import time
import traceback
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta,timezone
from extensions import db 
import ipaddress
import networkx as nx
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from pysnmp.carrier.asyncore.dgram import udp
from pysnmp.entity.rfc3413.oneliner import cmdgen
from pysnmp.hlapi import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    getCmd,
    nextCmd,
)
from sqlalchemy import and_, asc, desc, func, or_, text
from typing import List, Dict, Any, Tuple, Optional

from models.models import (
    Cabinet,
    ConnectionPath,
    Device,
    DiscoveryResult,
    DiscoveryTask,
    Interface,
    InterfaceRelationship,
    Location,
    LogicalTopology,
    TopologyLayout,
    TopologyLog,
    TopologySetting,
)

from models.config_models import SystemLog
from models.san_models import SanNode, SanLink
from utils.audit import log_audit
from utils.permission import permission_required
from utils.utils import parse_if_status, save_discovered_interfaces, snmp_get_device_info, snmp_get, snmp_walk
from utils.topology_discovery import (
    DeviceIndex,
    PROTOCOL_PRIORITY,
    expand_subnet_targets,
    normalize_mac as service_normalize_mac,
)

from utils.vm_oui import (
    classify_lldp_capabilities,
    classify_port_macs,
    detect_hypervisor_platform,
    normalize_mac as vm_normalize_mac,
    pick_physical_nic_mac,
)

topology_bp = Blueprint('topology', __name__, url_prefix='/topology')

# 全局线程池，最大并发任务数可根据服务器性能调整
discovery_executor = ThreadPoolExecutor(max_workers=5)
# 用于停止任务的标志
stop_events = {}



import re

def detect_encoding_and_fix(text):
    """
    检测并修复中文编码问题
    """
    if not text:
        return text
    
    # 如果已经包含正常中文，只修复常见的编码错误
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in text)
    
    # 常见编码错误修复映射
    fix_map = {
        '¥': '楼',      # 常见于 "10楼" 显示为 "10¥"
        '\ufffd': '',    # 替换损坏字符（U+FFFD）
        'À': '楼',      
        'Â': '楼',      
        '¢': '楼',      
        '£': '楼',      
        '¨': '',         
        '©': '',         
        'ª': '',         
        '«': '',         
        '»': '',         
        '¿': '',         
        '½': '',         
        '¾': '',         
        '·': '',         
        'º': '',         
        '±': '',         
        '²': '',         
        '³': '',         
        '´': '',         
        'µ': '',         
        '¶': '',         
        '¸': '',         
        '¹': '',         
        '¼': '',         
        'A2': '楼',      # 某些编码变体
        'A5': '',        # 某些编码变体
        'C2': '',        # 某些编码变体
    }
    
    result = text
    for wrong, correct in fix_map.items():
        if wrong in result:
            result = result.replace(wrong, correct)
    
    # 如果修复后结果不同，打印日志
    if result != text and len(text) > 1:
        print(f"[编码修复] '{text}' -> '{result}'")
    
    return result


def decode_snmp_string(val):
    """
    解码 SNMP 字符串，支持中文，并去除 STRING/Hex-STRING 前缀
    """
    if not val:
        return ''
    
    result = ''
    
    if isinstance(val, str):
        result = val
    elif isinstance(val, bytes):
        # ===== 特殊处理：6 字节可能是 MAC 地址，4 字节可能是 IP =====
        if len(val) == 6:
            return ':'.join(f'{b:02x}' for b in val)
        if len(val) == 4:
            return '.'.join(str(b) for b in val)
        # 否则尝试文本解码
        for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030', 'cp936', 'latin1']:
            try:
                result = val.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            result = val.decode('latin1', errors='replace')
    else:
        result = str(val)
    
    # ===== 清理结果 =====
    # 1. 去除 STRING: 或 Hex-STRING: 前缀（支持多种格式）
    result = re.sub(r'^(STRING|Hex-STRING|OCTET STRING|INTEGER|Counter32|Gauge32|Timeticks|IP-Address)\s*[:=]?\s*"?', '', result, flags=re.IGNORECASE)
    
    # 2. 去除首尾引号
    result = result.strip('"').strip("'")
    
    # 3. 去除首尾空格
    result = result.strip()
    
    # 4. 处理 Hex-STRING 格式（如 "47 41 4D 2D 39 C2 A5"）
    # 检测是否为十六进制字符串
    hex_pattern = re.compile(r'^([0-9A-Fa-f]{2}\s*)+$')
    if hex_pattern.match(result):
        try:
            hex_bytes = bytes.fromhex(result.replace(' ', ''))
            
            # ===== 特殊处理：6 字节可能是 MAC 地址，4 字节可能是 IP =====
            if len(hex_bytes) == 6:
                # 保留 MAC 地址格式 (xx:xx:xx:xx:xx:xx)
                result = ':'.join(f'{b:02x}' for b in hex_bytes)
                return result
            elif len(hex_bytes) == 4:
                # 保留 IP 地址格式 (x.x.x.x)
                result = '.'.join(str(b) for b in hex_bytes)
                return result
            
            # 其他长度：尝试解码为文本
            decoded = None
            for encoding in ['gbk', 'utf-8', 'gb2312', 'gb18030', 'cp936']:
                try:
                    decoded = hex_bytes.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if decoded:
                # 进一步清理
                decoded = decoded.strip('"').strip("'")
                result = decoded
                print(f"[Hex解码] '{result}' -> '{decoded}'")
        except Exception as e:
            print(f"[Hex解码] 转换失败: {e}")
    
    # 5. 清理不可打印字符（保留中文、字母、数字、常见符号）
    result = ''.join(c for c in result if c.isprintable() or c in '\n\r\t')
    
    # 6. 去除空字符
    result = result.replace('\x00', '')
    
    # 7. 如果结果为空或只有空白，返回空
    if not result or result.isspace():
        return ''
    
    # 8. 调用编码修复
    result = detect_encoding_and_fix(result)
    
    return result


# ========== 非物理端口识别（模块级，所有发现函数共享） ==========

NON_PHYSICAL_PORT_PATTERNS = [
    r'^Cellular\d',           # 蜂窝模块端口（路由器内置 4G/5G 模块）
    r'^Aux\d',                # 辅助端口
    r'^NULL\d',               # NULL 虚拟接口
    r'^Loopback\d',           # 环回口
    r'^Vlanif\d',             # VLAN 三层接口
    r'^Vlan-?Interface\d',    # VLAN 接口（变体）
    r'^Tunnel\d',             # VPN 隧道
    r'^Dialer\d',             # 拨号接口
    r'^Virtual-',             # 虚拟模板
    r'^VirtualAccess\d',      # 虚拟接入口
    r'^VoIP',                 # VoIP null 接口
    r'^M-GE',                 # 管理口
]


def is_non_physical_port(port_name):
    """判断端口名是否是非物理端口（不应出现在拓扑链路中）"""
    if not port_name or port_name in ('unknown', ''):
        return False  # 未知端口，不过滤
    for pattern in NON_PHYSICAL_PORT_PATTERNS:
        if re.match(pattern, port_name, re.IGNORECASE):
            return True
    return False


def find_real_physical_port(target_device_id, target_ip, community, bad_port):
    """
    尝试为非物理端口找到真正的物理端口。
    优先查数据库 Interface 表，其次 SNMP 查询。
    返回 (real_port_name, source) 或 (None, None)。
    """
    if not target_device_id:
        return None, None

    # 1. 查数据库：找目标设备 UP 状态的物理以太网口
    try:
        interfaces = Interface.query.filter(
            Interface.device_id == target_device_id,
            Interface.oper_status == 'up',
            Interface.name.notlike('Vlan%'),
            Interface.name.notlike('Loop%'),
            Interface.name.notlike('Tunnel%'),
            Interface.name.notlike('NULL%'),
            Interface.name.notlike('Aux%'),
            Interface.name.notlike('Cellular%'),
        ).order_by(Interface.speed.desc()).limit(3).all()

        if interfaces:
            # 排除管理口（速度通常很低或为 0）
            for iface in interfaces:
                if iface.speed and iface.speed >= 100:
                    return iface.name, 'db_up'
            # 如果所有接口 speed 都为 0，取第一个
            return interfaces[0].name, 'db_up'
    except Exception as e:
        print(f"[端口修正] 查数据库接口失败: {e}")

    # 2. 尝试 SNMP 查询目标设备
    if target_ip and community:
        try:
            ifaces = discover_interfaces_via_snmp(target_ip, community)
            for iface in ifaces:
                name = iface.get('name', '')
                if is_non_physical_port(name):
                    continue
                if iface.get('oper_status', '').lower() == 'up':
                    return name, 'snmp'
        except Exception as e:
            print(f"[端口修正] SNMP 查询 {target_ip} 失败: {e}")

    return None, None


def is_snmp_available(ip, community='public', timeout=3, retries=2):
    """统一使用 SnmpClient 做真实 SNMP GET 检测（不再依赖 UDP connect / 外部 snmpget）。"""
    from utils.topology_discovery import is_snmp_available as _check
    return _check(ip, community=community, timeout=timeout)


def check_snmp_with_retry(ip, community='public', max_attempts=2):
    """保留兼容入口：直接走统一 SNMP 检测。"""
    return is_snmp_available(ip, community=community, timeout=3)



# ---------- 辅助函数 ----------
def normalize_mac(mac):
    """
    标准化MAC地址，支持多种输入格式
    始终返回完整的 12 位十六进制字符串
    
    示例：
    - 00:e0:4c:3e:0c:70 -> 00e04c3e0c70
    - 00e0-4c3e-0c70 -> 00e04c3e0c70
    - 0e04c3ec70 -> 00e04c3e0c70 (自动补前导0)
    - 00 E0 4C 3E 0C 70 -> 00e04c3e0c70
    - 8c:e6:66:67:34:42 -> 8ce666673442
    """
    if not mac:
        return ''
    
    # 移除所有分隔符，只保留十六进制字符
    hex_chars = ''.join(c for c in str(mac).lower() if c in '0123456789abcdef')
    
    # 如果为空，返回空
    if not hex_chars:
        return ''
    
    # 如果长度不足12位，补前导0
    if len(hex_chars) < 12:
        hex_chars = hex_chars.zfill(12)
        print(f"[MAC] 补前导0: {mac} -> {hex_chars}")
    
    # 如果长度大于12位，截取前12位
    if len(hex_chars) > 12:
        hex_chars = hex_chars[:12]
    
    return hex_chars

def find_device_by_mac_and_update(mac_address, ip_address=None, device_name=None):
    """通过 MAC 查找设备，支持多种MAC格式"""
    if not mac_address:
        return None
    
    target_norm = normalize_mac(mac_address)
    if not target_norm:
        return None
    
    updated = False
    devices = Device.query.all()
    
    for dev in devices:
        dev_mac_norm = normalize_mac(dev.mac_address or '')
        if dev_mac_norm == target_norm:
            # 找到设备，检查是否需要补充信息
            if ip_address and is_valid_target_ip(ip_address):
                if not dev.management_ip and not dev.ip_address:
                    dev.management_ip = ip_address
                    dev.ip_address = ip_address
                    updated = True
                    print(f"[IPMAC] 为设备 {dev.name} 补充管理 IP: {ip_address}")
                # 如果IP不一致，更新（以ARP表为准）
                elif dev.management_ip != ip_address and dev.ip_address != ip_address:
                    old_ip = dev.management_ip or dev.ip_address
                    dev.management_ip = ip_address
                    dev.ip_address = ip_address
                    updated = True
                    print(f"[IPMAC] 更新设备 {dev.name} IP: {old_ip} -> {ip_address}")
            
            if device_name and device_name != 'unknown' and device_name != dev.name:
                old_name = dev.name
                dev.name = device_name
                updated = True
                print(f"[IPMAC] 更新设备名称: {old_name} -> {device_name}")
            
            if updated:
                dev.updated_at = datetime.now(timezone.utc)
                db.session.commit()
            return dev
        
        # 也尝试通过设备名匹配
        if dev.name and dev.name.startswith('Device-'):
            name_mac = dev.name.replace('Device-', '').replace(':', '').replace('-', '').lower()
            if name_mac == target_norm:
                # 同样更新IP...
                if ip_address and is_valid_target_ip(ip_address):
                    if not dev.management_ip and not dev.ip_address:
                        dev.management_ip = ip_address
                        dev.ip_address = ip_address
                        updated = True
                        print(f"[IPMAC] 为设备 {dev.name} (通过名称匹配) 补充管理 IP: {ip_address}")
                    elif dev.management_ip != ip_address and dev.ip_address != ip_address:
                        old_ip = dev.management_ip or dev.ip_address
                        dev.management_ip = ip_address
                        dev.ip_address = ip_address
                        updated = True
                        print(f"[IPMAC] 更新设备 {dev.name} IP: {old_ip} -> {ip_address}")
                
                if updated:
                    dev.updated_at = datetime.now(timezone.utc)
                    db.session.commit()
                return dev
    
    return None

def is_valid_target_ip(ip):
    """IP有效性校验"""
    if not ip or ip == 'None' or isinstance(ip, (list, dict)):
        return False
    try:
        ip_obj = ipaddress.ip_address(str(ip))
        return ip_obj.version == 4 and not ip_obj.is_loopback and not ip_obj.is_unspecified
    except (ValueError, TypeError):
        return False

def get_device_name(device_id):
    """根据设备ID获取设备名称（用于前端显示）"""
    if not device_id:
        return None
    device = Device.query.get(device_id)
    return device.name if device else None



def get_or_create_device_by_ip(ip: str) -> Device:
    """
    根据 IP 获取设备，如果不存在则创建一个默认设备（name=unknown）
    """
    from datetime import datetime, timezone
    if not ip:
        return None

    device = Device.query.filter(
        (Device.management_ip == ip) |
        (Device.ip_address == ip)
    ).first()

    if device:
        return device

    # 库中不存在，创建新设备
    device = Device(
        name="unknown",
        management_ip=ip,
        ip_address=ip,
        status="unknown",
        device_type="network",  # 或 "server"，可按需调整
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    db.session.add(device)
    db.session.flush()  # 立刻写入，获取 device.id
    return device

# ====================== SNMP 工具函数 ======================
def find_device_by_mac(mac_address: str) -> Optional[Device]:
    """
    根据 MAC 地址查找设备（标准化匹配）
    """
    if not mac_address:
        return None
    
    # 标准化 MAC 地址（无分隔符小写）
    def normalize_mac(mac):
        if not mac:
            return ''
        return ''.join(c for c in mac.lower() if c in '0123456789abcdef')
    
    target_norm = normalize_mac(mac_address)
    
    # 查询数据库中的所有设备
    devices = Device.query.all()
    for dev in devices:
        dev_mac_norm = normalize_mac(dev.mac_address or '')
        if dev_mac_norm == target_norm:
            return dev
        
        # 也尝试通过设备名称匹配 Device-{MAC}
        if dev.name and dev.name.startswith('Device-'):
            name_mac = dev.name.replace('Device-', '').replace(':', '').lower()
            if name_mac == target_norm:
                return dev
    
    return None


def find_device_by_mac_and_update(mac_address: str, ip_address: str = None, device_name: str = None) -> Optional[Device]:
    """
    根据 MAC 地址查找设备，并可选地补充管理 IP 和设备名称。
    
    参数:
        mac_address: MAC 地址
        ip_address: 可选的 IP 地址，如果设备没有管理 IP 则补充
        device_name: 可选的设备名称，如果设备名称为 'unknown' 或 None 则补充
    
    返回:
        找到的设备对象，或 None
    """
    if not mac_address:
        return None
    
    # 标准化 MAC 地址（无分隔符小写）
    def normalize_mac(mac):
        if not mac:
            return ''
        return ''.join(c for c in mac.lower() if c in '0123456789abcdef')
    
    target_norm = normalize_mac(mac_address)
    updated = False
    
    # 查询数据库中的所有设备
    devices = Device.query.all()
    for dev in devices:
        dev_mac_norm = normalize_mac(dev.mac_address or '')
        if dev_mac_norm == target_norm:
            # 找到设备，检查是否需要补充信息
            # 补充管理 IP
            if ip_address and is_valid_target_ip(ip_address):
                if not dev.management_ip and not dev.ip_address:
                    dev.management_ip = ip_address
                    dev.ip_address = ip_address
                    updated = True
                    print(f"[设备更新] 为设备 {dev.name} (MAC {mac_address}) 补充管理 IP: {ip_address}")
                elif dev.management_ip != ip_address and dev.ip_address != ip_address:
                    # IP 不一致时，记录日志但不覆盖（避免错误覆盖）
                    print(f"[设备更新] 警告：设备 {dev.name} 已有 IP {dev.management_ip or dev.ip_address}，"
                          f"本次发现 IP {ip_address} 不一致，保留原 IP")
            
            # 补充设备名称（如果当前名称是 'unknown' 或 None）
            if device_name and device_name != 'unknown':
                if not dev.name or dev.name == 'unknown':
                    dev.name = device_name
                    updated = True
                    print(f"[设备更新] 为设备 (MAC {mac_address}) 补充名称: {device_name}")
            
            if updated:
                dev.updated_at = datetime.now(timezone.utc)
                db.session.commit()
            
            return dev
        
        # 也尝试通过设备名称匹配 Device-{MAC}
        if dev.name and dev.name.startswith('Device-'):
            name_mac = dev.name.replace('Device-', '').replace(':', '').lower()
            if name_mac == target_norm:
                # 同样补充信息
                if ip_address and is_valid_target_ip(ip_address):
                    if not dev.management_ip and not dev.ip_address:
                        dev.management_ip = ip_address
                        dev.ip_address = ip_address
                        updated = True
                        print(f"[设备更新] 为设备 {dev.name} (通过名称匹配) 补充管理 IP: {ip_address}")
                
                if device_name and device_name != 'unknown':
                    if not dev.name or dev.name == 'unknown':
                        dev.name = device_name
                        updated = True
                
                if updated:
                    dev.updated_at = datetime.now(timezone.utc)
                    db.session.commit()
                
                return dev
    
    return None

def get_remote_interface_by_mac(remote_ip, mac, community, timeout=3):
    """
    通过 SNMP 查询远程设备的接口表，找到具有指定 MAC 地址的接口名称。
    优先返回物理接口（ifType=6）且状态为 up 的接口。
    参数:
        remote_ip: 对端设备 IP
        mac: 源 MAC 地址 (格式 xx:xx:xx:xx:xx:xx)
        community: SNMP community
        timeout: 命令超时时间 (秒)
    返回:
        接口名称 (字符串) 或 None
    """
    import subprocess
    import re
    from flask import current_app
    logger = current_app.logger

    try:
        mac_clean = mac.replace(':', '').lower()

        # 1. 获取 ifPhysAddress 表 (MAC -> ifIndex)
        cmd_phys = ['snmpwalk', '-v', '2c', '-c', community, remote_ip, 'IF-MIB::ifPhysAddress']
        proc = subprocess.run(cmd_phys, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            logger.warning(f"snmpwalk ifPhysAddress 失败: {proc.stderr}")
            return None

        # 解析 ifPhysAddress，建立 MAC -> ifIndex 列表（一个MAC可能对应多个接口）
        mac_to_indices = {}
        for line in proc.stdout.strip().split('\n'):
            match = re.match(r'IF-MIB::ifPhysAddress\.(\d+)\s+=\s+STRING:\s+([0-9a-f:]+)', line, re.IGNORECASE)
            if match:
                idx = match.group(1)
                mac_addr = match.group(2).replace(':', '').lower()
                if mac_addr == mac_clean:
                    mac_to_indices.setdefault(mac_addr, []).append(idx)

        if mac_clean not in mac_to_indices:
            logger.debug(f"在对端 {remote_ip} 上未找到 MAC {mac}")
            return None

        candidate_indices = mac_to_indices[mac_clean]

        # 2. 获取这些接口的 ifType、ifOperStatus 和 ifDescr
        # 使用 snmpget 批量获取（为了效率，可一次性 walk 整表，但为了简洁这里逐个获取）
        interface_info = {}  # idx -> {'type': int, 'oper': int, 'name': str}
        for idx in candidate_indices:
            # 获取 ifType
            cmd_type = ['snmpget', '-v', '2c', '-c', community, remote_ip, f'IF-MIB::ifType.{idx}']
            proc_type = subprocess.run(cmd_type, capture_output=True, text=True, timeout=timeout)
            if_type = None
            if proc_type.returncode == 0:
                match_type = re.search(r'INTEGER:\s*(\d+)', proc_type.stdout)
                if match_type:
                    if_type = int(match_type.group(1))

            # 获取 ifOperStatus
            cmd_oper = ['snmpget', '-v', '2c', '-c', community, remote_ip, f'IF-MIB::ifOperStatus.{idx}']
            proc_oper = subprocess.run(cmd_oper, capture_output=True, text=True, timeout=timeout)
            oper_status = None
            if proc_oper.returncode == 0:
                match_oper = re.search(r'INTEGER:\s*(\d+)', proc_oper.stdout)
                if match_oper:
                    oper_status = int(match_oper.group(1))

            # 获取 ifDescr（接口名称）
            cmd_name = ['snmpget', '-v', '2c', '-c', community, remote_ip, f'IF-MIB::ifDescr.{idx}']
            proc_name = subprocess.run(cmd_name, capture_output=True, text=True, timeout=timeout)
            if_name = None
            if proc_name.returncode == 0:
                match_name = re.search(r'STRING:\s*(.+)', proc_name.stdout)
                if match_name:
                    if_name = match_name.group(1).strip()

            interface_info[idx] = {
                'type': if_type,
                'oper': oper_status,
                'name': if_name
            }

        # 3. 选择优先级：物理接口 (ifType=6) 且 oper=1 (up) > 物理接口 (任意状态) > 其他
        best_idx = None
        best_score = -1
        for idx, info in interface_info.items():
            score = 0
            if info['type'] == 6:  # ethernetCsmacd
                if info['oper'] == 1:
                    score = 100
                else:
                    score = 50
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx is not None:
            iface_name = interface_info[best_idx]['name']
            logger.info(f"在对端 {remote_ip} 上找到匹配接口: {iface_name} (索引 {best_idx}, 类型={interface_info[best_idx]['type']}, 状态={interface_info[best_idx]['oper']})")
            return iface_name
        else:
            logger.warning(f"在对端 {remote_ip} 上找到 MAC {mac} 但无有效接口（所有候选接口都不是物理类型）")
            # 可选：如果希望至少返回一个接口，可以返回第一个候选的名称
            # first_idx = candidate_indices[0]
            # return interface_info[first_idx]['name']
            return None

    except subprocess.TimeoutExpired:
        logger.warning(f"查询对端 {remote_ip} 接口信息超时")
        return None
    except Exception as e:
        logger.warning(f"获取对端 {remote_ip} 接口信息异常: {e}")
        return None



# ---------- 辅助函数 ----------
def get_current_user():
    """获取当前登录用户（示例，根据实际认证系统修改）"""
    from flask_login import current_user
    return current_user


def validate_csrf_token():
    """验证 CSRF token（根据实际实现调整）"""
    # 例如从请求头获取 X-CSRFToken，并与 session 中的 token 比对
    # 此处略，可在具体路由中通过 @csrf.exempt 跳过，或统一验证
    pass


def get_lldp_management_addresses(ip, community='public'):
    """
    通过 LLDP MIB 获取邻居的管理地址（IPv4）
    返回字典: {(time_mark, remote_index): management_ip}
    使用标准 OID: lldpRemManAddr (1.0.8802.1.1.2.1.4.2.1.1)
    """
    from utils.utils import snmp_walk
    import re
    
    oid_man_addr = '1.0.8802.1.1.2.1.4.2.1.1'  # lldpRemManAddr
    addr_map = {}
    
    # OID 前缀长度（固定部分）
    # .1.0.8802.1.1.2.1.4.2.1.1 共 12 个数字（从第一个点后算起）
    prefix_len = 12
    
    entries = snmp_walk(ip, oid_man_addr, community, timeout=10, retries=3)
    for oid_str, val in entries:
        parts = oid_str.split('.')
        if len(parts) < prefix_len + 4:
            continue
        
        # 提取 time_mark 和 remote_index
        # OID 结构: ... .1.0.8802.1.1.2.1.4.2.1.1.<time_mark>.<remote_index>.<subtype>.<addr_bytes...>
        time_mark = parts[prefix_len]
        remote_idx = parts[prefix_len + 1]
        subtype = parts[prefix_len + 2]  # 1 = IPv4
        
        if subtype != '1':
            continue  # 只处理 IPv4
        
        # 提取地址字节（从 prefix_len+3 到末尾）
        addr_bytes = parts[prefix_len + 3:]
        if len(addr_bytes) == 4:  # IPv4 地址由 4 个字节组成
            ip_str = '.'.join(addr_bytes)
            if is_valid_target_ip(ip_str):
                key = (time_mark, remote_idx)
                addr_map[key] = ip_str
                print(f"[LLDP] 邻居管理地址: time_mark={time_mark}, remote_idx={remote_idx} -> {ip_str}")
    
    return addr_map


def get_dot1d_base_port_ifindex(ip, community='public'):
    """获取 dot1dBasePort 到 ifIndex 的映射，返回 {dot1d_port: ifIndex}"""
    oid = '1.3.6.1.2.1.17.1.4.1.2'  # dot1dBasePortIfIndex
    entries = snmp_walk(ip, oid, community, timeout=10, retries=3)
    port_map = {}
    for oid_str, val in entries:
        parts = oid_str.split('.')
        if not parts:
            continue
        dot1d_port = parts[-1]
        if_index = str(val).strip()
        port_map[dot1d_port] = if_index
    return port_map


def get_arp_table(ip, community='public', version='2c'):
    """
    获取设备的 ARP 表
    确保 MAC 地址保持完整的 12 位十六进制格式
    """
    arp_entries = {}
    oid = '1.3.6.1.2.1.4.22.1.2'
    
    try:
        results = snmp_walk(ip, oid, community, version=version, timeout=5)
        
        for oid_str, value in results:
            # 提取 IP 地址（OID 最后4段）
            parts = oid_str.split('.')
            if len(parts) >= 4:
                ip_addr = '.'.join(parts[-4:])
                mac_raw = str(value).strip('"')
                
                # ========== 修复：确保 MAC 地址是完整的 12 位 ==========
                # 移除所有分隔符
                mac_clean = ''.join(c for c in mac_raw.lower() if c in '0123456789abcdef')
                
                # 如果长度不足12位，补前导0
                if len(mac_clean) < 12:
                    mac_clean = mac_clean.zfill(12)
                
                # 确保长度是12位
                if len(mac_clean) == 12:
                    arp_entries[ip_addr] = mac_clean
                    
    except Exception as e:
        print(f"[ARP] 获取 ARP 表失败: {e}")
    
    return arp_entries

def get_interface_by_mac_on_device(device_ip, target_mac, community, timeout=3):
    """
    在指定设备上通过 SNMP 查找某个 MAC 地址对应的端口名。
    target_mac: 需要查找的 MAC 地址（小写，带冒号格式）
    """
    try:
        mac_table = get_mac_table(device_ip, community)
        if not mac_table:
            print(f"[DEBUG] 设备 {device_ip} 未返回 MAC 表")
            return None

        dot1d_to_ifindex = get_dot1d_base_port_ifindex(device_ip, community)
        ifaces = discover_interfaces_via_snmp(device_ip, community)
        ifname_map = {iface['index']: iface['name'] for iface in ifaces}

        target_norm = ''.join(c for c in target_mac.lower() if c in '0123456789abcdef')
        for mac, dot1d_port in mac_table.items():
            mac_norm = ''.join(c for c in mac.lower() if c in '0123456789abcdef')
            if mac_norm == target_norm:
                if_index = dot1d_to_ifindex.get(dot1d_port)
                if if_index and if_index in ifname_map:
                    return ifname_map[if_index]
                else:
                    print(f"[DEBUG] 找到 MAC 但无法转换端口: dot1d_port={dot1d_port}, if_index={if_index}")
        return None
    except Exception as e:
        print(f"[DEBUG] SNMP 查询设备 {device_ip} 上 MAC {target_mac} 失败: {e}")
        return None



def get_mac_table(ip, community='public'):
    """
    获取 MAC 地址表，支持两种 OID：
    1. 1.3.6.1.2.1.17.7.1.2.2.1.2 (Q-BRIDGE-MIB)
    2. 1.3.6.1.2.1.17.4.3.1.2 (BRIDGE-MIB)
    """
    mac_table = {}
    oid_list = [
        '1.3.6.1.2.1.17.7.1.2.2.1.2',   # Q-BRIDGE
        '1.3.6.1.2.1.17.4.3.1.2'        # BRIDGE-MIB
    ]
    entries = None
    for oid in oid_list:
        entries = snmp_walk(ip, oid, community, timeout=10, retries=2)
        if entries:
            print(f"[DEBUG] 使用 OID {oid} 获取到 {len(entries)} 条 MAC 条目")
            break
    if not entries:
        print(f"[DEBUG] 未从 {ip} 获取到任何 MAC 条目")
        return {}

    for oid_str, port_val in entries:
        parts = oid_str.split('.')
        if len(parts) < 6:
            continue
        mac_parts = parts[-6:]
        # 转换为标准 MAC 格式（小写，两位十六进制）
        mac_str = ':'.join(f'{int(p):02x}' for p in mac_parts)
        mac_table[mac_str] = str(port_val).strip()
    return mac_table




def run_protocol_discovery(task, stop_event, app=None):
    """
    执行协议发现（LLDP/CDP/SNMP MAC），自动复用数据库中已有设备
    app: Flask 应用实例，用于在子线程中创建上下文
    """
    from models.models import db, Device, Interface, ConnectionPath
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import ipaddress
    import traceback
    import re
    # ========== 辅助函数：统一使用 SnmpClient 检测 SNMP 可用性 ==========


    def normalize_mac(mac):
        if not mac:
            return ''
        return ''.join(c for c in mac.lower() if c in '0123456789abcdef')

    def is_valid_target_ip(ip):
        if not ip or ip == 'None' or isinstance(ip, (list, dict)):
            return False
        try:
            ip_obj = ipaddress.ip_address(str(ip))
            return ip_obj.version == 4 and not ip_obj.is_loopback and not ip_obj.is_unspecified
        except (ValueError, TypeError):
            return False

    # ========== 预加载设备索引（供解析设备种子和发现循环使用）==========
    device_index = DeviceIndex()
    device_index.load()

    # ========== 解析目标 ==========
    target_value = task.get_target_value()
    seeds = target_value.get('seeds', [])
    subnets = target_value.get('subnets', [])
    device_ids = target_value.get('device_ids', [])

    scan_queue = []
    for seed in seeds:
        if is_valid_target_ip(seed):
            scan_queue.append((seed, 1))
    
    for subnet_str in subnets:
        try:
            max_subnet_hosts = int(target_value.get('max_subnet_hosts', 4096) or 4096)
            for ip_str in expand_subnet_targets(subnet_str, max_hosts=max_subnet_hosts):
                if is_valid_target_ip(ip_str):
                    scan_queue.append((ip_str, 1))
        except Exception as e:
            print(f"[协议发现] 子网解析失败 {subnet_str}: {e}")
    
    for dev_id in device_ids:
        dev = device_index.by_id_get(dev_id)
        if dev:
            ip = dev.management_ip or dev.ip_address
            if is_valid_target_ip(ip):
                scan_queue.append((ip, 1))

    scan_queue = list(dict.fromkeys(scan_queue))
    print(f"[协议发现] 待扫描设备: {len(scan_queue)} 个")

    discovered_ips = set()
    lldp_seen_ips = set()   # 本次成功读到 LLDP 表（非空）的设备 IP，用于过期链路清理
    all_interfaces = {}
    all_connections = []

    # ========== 预先提取 task 属性（避免跨线程 ORM 懒加载） ==========
    max_depth = task.max_depth or 3
    snmp_community = task.snmp_community or 'public'
    use_lldp = task.use_lldp
    use_cdp = task.use_cdp
    use_snmp_mac = getattr(task, 'use_snmp_mac', True)
    max_threads = task.max_threads or 5
    auto_save = task.auto_save
    snmp_timeout = task.snmp_timeout or 5
    snmp_retries = task.snmp_retries or 2

    total_steps = max(len(scan_queue) * max_depth, 1)
    step = 0

    # ========== 单个设备发现函数 ==========
 
    def discover_device(ip, depth):
        """单个设备的发现任务"""
        # ===== 使用传入的 app 创建上下文 =====
        with app.app_context():
            if ip in discovered_ips or depth > max_depth:
                return None

            # 从预加载索引获取设备
            device = device_index.by_ip_get(ip)
            
            # 优先使用数据库中存储的 community
            community = snmp_community
            if device and device.snmp_community:
                community = device.snmp_community
                print(f"[协议发现] {ip} 使用数据库 community: {community}")
            else:
                print(f"[协议发现] {ip} 使用任务默认 community: {community}")

            # 统一 SNMP 可用性检测（真实 sysDescr GET）
            if not is_snmp_available(ip, community, timeout=max(2, snmp_timeout or 2)):
                print(f"[协议发现] {ip} SNMP服务未响应 (community: {community})，跳过")
                return None

            print(f"[协议发现] {ip} SNMP服务可用，开始发现")

            result = {
                'ip': ip,
                'depth': depth,
                'interfaces': [],
                'lldp_neighbors': [],
                'cdp_neighbors': [],
                'mac_neighbors': []
            }

            # 构建接口映射
            interface_map = {}

            # 1. 发现接口
            try:
                interfaces = discover_interfaces_via_snmp(ip, community)
                result['interfaces'] = interfaces
                for iface in interfaces:
                    interface_map[str(iface['index'])] = iface['name']
            except Exception as e:
                print(f"[协议发现] {ip} 接口发现失败: {e}")

            # 2. LLDP 发现
            if use_lldp:
                try:
                    lldp_neighbors = discover_lldp_neighbors(ip, community)
                    print(f"[LLDP] 从 {ip} 发现 {len(lldp_neighbors)} 个邻居")
                    
                    addr_map = get_lldp_management_addresses(ip, community)
                    
                    for n in lldp_neighbors:
                        # ===== 获取并清理邻居名称 =====
                        remote_sysname = n.get('remote_sysname', '').strip()
                        
                        # 如果名称以 "STRING:" 开头，去除（兜底处理）
                        if remote_sysname.startswith('STRING:'):
                            remote_sysname = remote_sysname.replace('STRING:', '').strip().strip('"')
                            n['remote_sysname'] = remote_sysname
                        
                        # 如果名称是十六进制字符串格式，尝试转换
                        if remote_sysname and re.match(r'^([0-9A-F]{2}\s*)+$', remote_sysname, re.IGNORECASE):
                            try:
                                hex_bytes = bytes.fromhex(remote_sysname.replace(' ', ''))
                                for encoding in ['gbk', 'utf-8', 'gb2312']:
                                    try:
                                        remote_sysname = hex_bytes.decode(encoding).strip('"')
                                        n['remote_sysname'] = remote_sysname
                                        print(f"[LLDP] 十六进制转换: {remote_sysname}")
                                        break
                                    except UnicodeDecodeError:
                                        continue
                            except Exception as e:
                                print(f"[LLDP] 十六进制转换失败: {e}")
                        
                        neighbor_ip = resolve_neighbor_ip_enhanced(n, addr_map, device_index=device_index)
                        neighbor_mac = extract_mac_from_chassis(n.get('remote_chassis', ''))
                        
                        has_ip = neighbor_ip and is_valid_target_ip(neighbor_ip)
                        has_mac = neighbor_mac and len(normalize_mac(neighbor_mac)) == 12
                        matched_device = None  # 提前初始化

                        # ===== 如果 MAC 有效，尝试通过 MAC 查找已有设备 =====
                        if has_mac and not matched_device:
                            matched_device = device_index.by_mac_get(neighbor_mac)
                            if matched_device:
                                print(f"[LLDP] 通过 MAC 匹配到设备: {matched_device.name} ({neighbor_mac})")
                                # 补充 IP（如果设备有 IP 但 neighbor_ip 为空）
                                if not has_ip:
                                    dev_ip = matched_device.management_ip or matched_device.ip_address
                                    if dev_ip and is_valid_target_ip(dev_ip):
                                        neighbor_ip = dev_ip
                                        has_ip = True
                                        print(f"[LLDP] 从匹配设备补充 IP: {dev_ip}")

                        # ===== 检查名称是否有效 =====
                        valid_name = False
                        if remote_sysname:
                            # 清理名称，检查是否包含有效字符
                            clean_name = ''.join(c for c in remote_sysname if c.isalnum() or c in '-_.' or '\u4e00' <= c <= '\u9fff')
                            if len(clean_name) >= 2:
                                valid_name = True
                        
                        if not has_ip and not has_mac:
                            if valid_name:
                                # 精确匹配
                                matched_device = device_index.by_name_exact(remote_sysname)
                                if not matched_device:
                                    matched_device = device_index.by_name_fuzzy(remote_sysname)

                                if matched_device:
                                    neighbor_ip = matched_device.management_ip or matched_device.ip_address
                                    if neighbor_ip and is_valid_target_ip(neighbor_ip):
                                        has_ip = True
                                        print(f"[LLDP] 通过名称匹配到设备: {matched_device.name} -> {neighbor_ip}")
                                    if not has_ip and matched_device.mac_address:
                                        neighbor_mac = matched_device.mac_address
                                        if len(normalize_mac(neighbor_mac)) == 12:
                                            has_mac = True
                                            print(f"[LLDP] 通过名称匹配到设备MAC: {matched_device.name} -> {neighbor_mac}")

                                # 未匹配到任何已有设备：无 IP、无 MAC、名称也无匹配 → 跳过，
                                # 不再自动创建 device_type=unknown 的占位设备（纯死端，只会污染 CMDB）
                                if not matched_device:
                                    print(f"[LLDP] 跳过邻居 '{remote_sysname}'：无有效 IP/MAC 且未匹配到已有设备，不创建占位")
                                    continue
                            else:
                                print(f"[LLDP] 跳过邻居 '{remote_sysname}'：无有效 IP 或 MAC，且名称无效")
                                continue

                        src_iface = n.get('local_interface_name', '')
                        if not src_iface or src_iface.startswith('Port-'):
                            # ===== 如果 interface_map 为空，尝试重新获取接口信息 =====
                            if not interface_map:
                                try:
                                    ifaces = discover_interfaces_via_snmp(ip, community)
                                    for iface in ifaces:
                                        interface_map[str(iface['index'])] = iface['name']
                                    if interface_map:
                                        print(f"[LLDP] 二次获取接口映射成功: {len(interface_map)} 个接口")
                                except Exception as e:
                                    print(f"[LLDP] 二次获取接口映射失败: {e}")
                            local_ifindex = n.get('local_ifindex', '')
                            if local_ifindex and local_ifindex in interface_map:
                                src_iface = interface_map[local_ifindex]
                            else:
                                # 不再用无意义的 Port-{ifindex} / Port-{lldp_port} 兜底名
                                src_iface = 'unknown'

                        dst_iface = n.get('remote_port', '').strip() or n.get('remote_port_desc', '').strip()
                        if not dst_iface:
                            # 不再用无意义的 Port-{remote_idx}（remote_idx 只是 OID 索引，不是真实端口名）
                            dst_iface = 'unknown'

                        # 两端端口都无法解析为真实名称时，该连接无拓扑价值，跳过（避免 Port-xxx 空壳连接）
                        if src_iface == 'unknown' and dst_iface == 'unknown':
                            print(f"[LLDP] 跳过连接：两端端口均未知 ({remote_sysname})")
                            continue

                        # ===== 邻居类型分类：交换机(级联) / 路由器 / 服务器主机 =====
                        neighbor_class = classify_lldp_capabilities(n.get('cap_enabled', ''))
                        # 通过 sysDesc/sysName 关键字识别虚拟化平台（宿主机）
                        platform = detect_hypervisor_platform(
                            n.get('remote_sysdesc', '') or n.get('remote_sysname', '')
                        )
                        if neighbor_class == 'switch':
                            neighbor_type = 'switch'
                        elif neighbor_class == 'router':
                            neighbor_type = 'router'
                        elif neighbor_class == 'host':
                            neighbor_type = 'hypervisor' if platform else 'server'
                        else:
                            neighbor_type = 'hypervisor' if platform else 'unknown'

                        result['lldp_neighbors'].append({
                            'source_ip': ip,
                            'source_device_id': device.id if device else None,
                            'source_port': src_iface,
                            'source_port_desc': n.get('local_port_desc', ''),
                            'target_ip': neighbor_ip,
                            'target_port': dst_iface,
                            'target_port_desc': n.get('remote_port_desc', ''),
                            'protocol': 'lldp',
                            'remote_sysname': n.get('remote_sysname', ''),
                            'remote_chassis': n.get('remote_chassis', ''),
                            'remote_mac': neighbor_mac,
                            'target_device_id': matched_device.id if matched_device else None,
                            'neighbor_type': neighbor_type,
                            'hypervisor_platform': platform,
                            'neighbor_class': neighbor_class,
                        })
                        
                except Exception as e:
                    print(f"[LLDP] {ip} 发现失败: {e}")

            # 3. CDP 发现
            if use_cdp:
                try:
                    cdp_neighbors = discover_cdp_neighbors(ip, community)
                    print(f"[CDP] 从 {ip} 发现 {len(cdp_neighbors)} 个邻居")
                    
                    for n in cdp_neighbors:
                        neighbor_ip = n.get('remote_ip')
                        neighbor_mac = n.get('remote_mac', '')
                        
                        has_ip = neighbor_ip and is_valid_target_ip(neighbor_ip)
                        has_mac = neighbor_mac and len(normalize_mac(neighbor_mac)) == 12
                        
                        if not has_ip and not has_mac:
                            print(f"[CDP] 跳过邻居 '{n.get('remote_device', '')}'：无有效 IP 或 MAC")
                            continue
                        
                        local_iface = interface_map.get(n.get('local_ifindex', ''), n.get('local_interface', ''))
                        
                        result['cdp_neighbors'].append({
                            'source_ip': ip,
                            'source_device_id': device.id if device else None,
                            'source_port': local_iface,
                            'target_ip': neighbor_ip,
                            'target_port': n.get('remote_port', 'unknown'),
                            'protocol': 'cdp',
                            'remote_sysname': n.get('remote_device', ''),
                            'remote_chassis': '',
                            'remote_mac': neighbor_mac
                        })
                        
                except Exception as e:
                    print(f"[CDP] {ip} 发现失败: {e}")

            # 4. SNMP MAC 发现
            if use_snmp_mac:
                try:
                    mac_neighbors = discover_neighbors_via_snmp_mac(ip, community, interface_map, device_index=device_index)
                    print(f"[SNMP MAC] 从 {ip} 发现 {len(mac_neighbors)} 个邻居")
                    
                    for n in mac_neighbors:
                        neighbor_ip = n.get('ip')
                        neighbor_mac = n.get('remote_mac', '') or n.get('mac', '')
                        
                        has_ip = neighbor_ip and is_valid_target_ip(neighbor_ip)
                        has_mac = neighbor_mac and len(normalize_mac(neighbor_mac)) == 12
                        
                        if not has_ip and not has_mac:
                            print(f"[SNMP MAC] 跳过邻居：无有效 IP 或 MAC")
                            continue
                        
                        result['mac_neighbors'].append({
                            'source_ip': ip,
                            'source_device_id': device.id if device else None,
                            'source_port': n.get('local_interface', 'unknown'),
                            'target_ip': neighbor_ip,
                            'target_port': n.get('remote_interface', 'unknown'),
                            'protocol': 'snmp_mac',
                            'remote_sysname': '',
                            'remote_chassis': '',
                            'remote_mac': neighbor_mac,
                            'neighbor_type': n.get('neighbor_type', 'device'),
                            'vm_mac_count': n.get('vm_mac_count', 0),
                            'hypervisor_platform': n.get('hypervisor_platform', ''),
                        })
                        
                except Exception as e:
                    print(f"[SNMP MAC] {ip} 发现失败: {e}")

            return result

    # ========== 使用线程池多轮并发发现（BFS） ==========
    # 解决级联交换机多级发现问题：每轮发现一批设备的邻居，
    # 将新发现的邻居IP加入队列，下一轮继续发现，直到没有新邻居或达到最大深度
    max_workers = min(max_threads, 10)
    print(f"[协议发现] 使用 {max_workers} 个并发线程，最大深度 {max_depth}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        pending_ips = set()      # 已提交但尚未处理完成的IP
        scan_queue_map = {}      # IP -> depth，用于快速查找

        # 初始化队列
        for ip, depth in scan_queue:
            scan_queue_map[ip] = depth

        round_num = 0

        while True:
            round_num += 1
            # 找出尚未发现且尚未提交的IP
            new_ips = [(ip, depth) for ip, depth in scan_queue
                       if ip not in discovered_ips and ip not in pending_ips]

            if not new_ips:
                print(f"[协议发现] 第 {round_num} 轮：没有新的IP需要发现，结束多轮发现")
                break

            print(f"[协议发现] ====== 第 {round_num} 轮发现，新发现 {len(new_ips)} 个IP ======")

            # 提交本轮所有新IP的发现任务
            round_futures = {}
            for ip, depth in new_ips:
                pending_ips.add(ip)
                future = executor.submit(discover_device, ip, depth)
                round_futures[future] = (ip, depth)

            new_neighbors_found = False

            for future in as_completed(round_futures):
                if stop_event.is_set():
                    print("[协议发现] 收到停止信号")
                    for f in round_futures:
                        f.cancel()
                    break

                ip, depth = round_futures[future]
                try:
                    result = future.result(timeout=60)

                    if result is None:
                        discovered_ips.add(ip)
                        continue

                    discovered_ips.add(ip)
                    if result.get('lldp_neighbors'):
                        lldp_seen_ips.add(ip)
                    step += 1
                    # 动态更新进度（基于已发现的IP数量）
                    task.progress = min(int(step / max(step + len([q for q in scan_queue if q[0] not in discovered_ips]), 1) * 100), 99)
                    db.session.commit()

                    # 保存接口
                    if result['interfaces']:
                        all_interfaces[ip] = result['interfaces']
                        device = device_index.by_ip_get(ip)
                        if device and auto_save:
                            for iface in result['interfaces']:
                                existing = Interface.query.filter_by(
                                    device_id=device.id,
                                    name=iface['name']
                                ).first()
                                if not existing:
                                    new_iface = Interface(
                                        device_id=device.id,
                                        name=iface['name'],
                                        snmp_index=iface['index'],
                                        type='Ethernet',
                                        speed=iface.get('speed', 0),
                                        mtu=iface.get('mtu', 1500),
                                        mac_address=iface.get('mac_address', ''),
                                        oper_status=iface.get('oper_status', 'unknown')
                                    )
                                    db.session.add(new_iface)
                            db.session.commit()

                    # 处理邻居 —— 将新邻居加入队列供下一轮发现
                    all_neighbors = result['lldp_neighbors'] + result['cdp_neighbors'] + result['mac_neighbors']
                    for conn in all_neighbors:
                        all_connections.append(conn)
                        neighbor_ip = conn.get('target_ip')
                        neighbor_depth = depth + 1

                        # 检查深度限制
                        if neighbor_depth > max_depth:
                            print(f"[协议发现] 邻居 {neighbor_ip} 深度 {neighbor_depth} 超过最大深度 {max_depth}，跳过")
                            continue

                        if neighbor_ip and neighbor_ip not in discovered_ips:
                            if neighbor_ip not in scan_queue_map:
                                scan_queue.append((neighbor_ip, neighbor_depth))
                                scan_queue_map[neighbor_ip] = neighbor_depth
                                new_neighbors_found = True
                                print(f"[协议发现] 新邻居入队: {neighbor_ip} (深度 {neighbor_depth})")

                    print(f"[协议发现] {ip} (深度 {depth}) 发现完成，当前进度: 已发现 {step} 个设备，"
                          f"队列中还有 {len(scan_queue) - step} 个IP待扫描")

                except Exception as e:
                    print(f"[协议发现] {ip} 处理异常: {e}")
                    traceback.print_exc()
                    discovered_ips.add(ip)

            if stop_event.is_set():
                break

            if not new_neighbors_found:
                print(f"[协议发现] 第 {round_num} 轮未发现新邻居，多级发现结束")
                break

        print(f"[协议发现] 多轮发现完成，共 {round_num} 轮，发现 {len(discovered_ips)} 个设备")

    # ========== 去重：方向无关的去重 key，不修改原始连接数据 ==========
    def dedup_key(conn):
        """生成方向无关的去重 key，不修改连接 dict，保留 device_id 供后续使用"""
        ip_a = conn.get('source_ip', '')
        ip_b = conn.get('target_ip', '')
        port_a = conn.get('source_port', '')
        port_b = conn.get('target_port', '')
        # 方向无关：较小 IP 永远放前面
        if ip_a and ip_b and str(ip_a) > str(ip_b):
            ip_a, ip_b = ip_b, ip_a
            port_a, port_b = port_b, port_a
        return (str(ip_a), str(port_a), str(ip_b), str(port_b),
                str(conn.get('remote_mac', '') or ''))

    unique = {}
    for conn in all_connections:
        key = dedup_key(conn)
        if key not in unique:
            unique[key] = conn
    all_connections = list(unique.values())

    print(f"[协议发现] 去重后连接数: {len(all_connections)}")

    task.discovered_count = len(discovered_ips)
    task.connection_count = len(all_connections)
    db.session.commit()

    # ========== 保存结果 ==========
    if auto_save:
        valid_connections = []
        for conn in all_connections:
            has_ip = conn.get('target_ip') and is_valid_target_ip(conn['target_ip'])
            has_mac = conn.get('remote_mac') and len(normalize_mac(conn['remote_mac'])) == 12
            if has_ip or has_mac:
                valid_connections.append(conn)

        print(f"[协议发现] 有效连接数: {len(valid_connections)} / {len(all_connections)}")
        if valid_connections:
            save_discovery_results(task.id, valid_connections, discovered_ips, lldp_seen_ips)
        else:
            print("[协议发现] 没有有效的连接需要保存")

    print(f"[协议发现] 任务 {task.id} 完成")








    
def extract_mac_from_chassis(chassis_string):
    """
    从 chassis 字符串中提取 MAC 地址
    支持格式: 00:11:22:33:44:55, 00-11-22-33-44-55, 001122334455, "00 11 22 33 44 55"
    """
    if not chassis_string:
        return None
    
    chassis = str(chassis_string).strip()
    
    # 移除常见的 "MAC:" 前缀
    chassis = re.sub(r'^(MAC:|mac:|Mac:)', '', chassis)
    chassis = chassis.strip()
    
    # 格式1: xx:xx:xx:xx:xx:xx 或 xx-xx-xx-xx-xx-xx
    mac_match = re.search(r'([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}', chassis)
    if mac_match:
        return mac_match.group()
    
    # 格式2: "xx xx xx xx xx xx" (空格分隔)
    mac_match = re.search(r'([0-9a-fA-F]{2}\s){5}[0-9a-fA-F]{2}', chassis)
    if mac_match:
        mac = mac_match.group().replace(' ', ':').lower()
        return mac
    
    # 格式3: xxxxxxxxxxxx (12位十六进制，无分隔符)
    mac_match = re.search(r'\b[0-9a-fA-F]{12}\b', chassis)
    if mac_match:
        mac = mac_match.group()
        return ':'.join(mac[i:i+2] for i in range(0, 12, 2)).lower()
    
    return None

def run_ipmac_discovery(task, stop_event):
    """
    执行 IP/MAC 发现任务（完整版）
    - 核心和接入交换机均支持级联端口过滤（端口上 MAC 数 ≥2 视为级联，跳过）
    - 有 IP 设备通过 ARP 表匹配
    - 无 IP 设备通过 MAC 表直接发现，使用 MAC 地址命名
    - 自动跳过已存在于数据库中的连接（避免与 LLDP 等重复）
    - 对于无 IP 但已在数据库中的设备，利用其管理 IP 通过 SNMP 获取对端接口名
    - 【新增】发现完成后，通过核心 ARP 表为有 MAC 无 IP 的设备补充管理 IP
    """
    print(f"[IPMAC] ========== 开始 IP/MAC 发现，任务 ID: {task.id} ==========")
    from models.models import Device, Interface, ConnectionPath, db
    from datetime import datetime, timezone

    # 辅助函数：标准化 MAC 地址（无分隔符小写）
    def normalize_mac(mac):
        if not mac:
            return ''
        return ''.join(c for c in mac.lower() if c in '0123456789abcdef')

    # ========== 增强版：通过 MAC 查找设备并补充 IP ==========
    def find_device_by_mac_and_update(mac_address, ip_address=None, device_name=None):
        """通过 MAC 查找设备，如果提供了 IP 且设备没有管理 IP，则补充"""
        if not mac_address:
            return None
        
        target_norm = normalize_mac(mac_address)
        updated = False
        
        devices = Device.query.all()
        for dev in devices:
            dev_mac_norm = normalize_mac(dev.mac_address or '')
            if dev_mac_norm == target_norm:
                # 找到设备，检查是否需要补充信息
                if ip_address and is_valid_target_ip(ip_address):
                    if not dev.management_ip and not dev.ip_address:
                        dev.management_ip = ip_address
                        dev.ip_address = ip_address
                        updated = True
                        print(f"[IPMAC] 为设备 {dev.name} (MAC {mac_address}) 补充管理 IP: {ip_address}")
                    elif dev.management_ip != ip_address and dev.ip_address != ip_address:
                        print(f"[IPMAC] 警告：设备 {dev.name} 已有 IP {dev.management_ip or dev.ip_address}，"
                              f"本次发现 IP {ip_address} 不一致，保留原 IP")
                
                if device_name and device_name != 'unknown':
                    if not dev.name or dev.name == 'unknown':
                        dev.name = device_name
                        updated = True
                        print(f"[IPMAC] 为设备 (MAC {mac_address}) 补充名称: {device_name}")
                
                if updated:
                    dev.updated_at = datetime.now(timezone.utc)
                    db.session.commit()
                return dev
            
            # 也尝试通过设备名称匹配 Device-{MAC}
            if dev.name and dev.name.startswith('Device-'):
                name_mac = dev.name.replace('Device-', '').replace(':', '').lower()
                if name_mac == target_norm:
                    if ip_address and is_valid_target_ip(ip_address):
                        if not dev.management_ip and not dev.ip_address:
                            dev.management_ip = ip_address
                            dev.ip_address = ip_address
                            updated = True
                            print(f"[IPMAC] 为设备 {dev.name} (通过名称匹配) 补充管理 IP: {ip_address}")
                    
                    if device_name and device_name != 'unknown':
                        if not dev.name or dev.name == 'unknown':
                            dev.name = device_name
                            updated = True
                    
                    if updated:
                        dev.updated_at = datetime.now(timezone.utc)
                        db.session.commit()
                    return dev
        
        return None

    core_device_id = task.core_device_id
    access_device_ids = task.get_access_device_ids()
    print(f"[IPMAC] 核心设备 ID: {core_device_id}, 接入设备 IDs: {access_device_ids}")

    # ---------- 预加载现有连接（用于快速去重）----------
    existing_conns = set()
    all_conns = ConnectionPath.query.with_entities(
        ConnectionPath.source_device_id, ConnectionPath.source_port,
        ConnectionPath.target_device_id, ConnectionPath.target_port
    ).all()
    for src_dev, src_port, tgt_dev, tgt_port in all_conns:
        existing_conns.add((src_dev, src_port, tgt_dev, tgt_port))
        existing_conns.add((tgt_dev, tgt_port, src_dev, src_port))
    print(f"[IPMAC] 已加载 {len(all_conns)} 条现有连接用于去重")

    # ==================== 1. 核心交换机处理 ====================
    core = Device.query.get(core_device_id)
    if not core:
        error_msg = f"核心交换机不存在 ID: {core_device_id}"
        print(f"[IPMAC] 错误：{error_msg}")
        task.last_error = error_msg
        task.status = 'failed'
        db.session.commit()
        return

    core_ip = core.management_ip or core.ip_address
    core_community = core.snmp_community or 'public'
    print(f"[IPMAC] 核心 IP: {core_ip}, 团体名: {core_community}")

    # 获取 ARP 表
    try:
        arp_entries = get_arp_table(core_ip, core_community)
        print(f"[IPMAC] ARP 表条目数: {len(arp_entries)}")
        
        # 调试：打印 ARP 表内容
        for ip, mac in arp_entries.items():
            print(f"[IPMAC] ARP 原始: {ip} -> {mac}")
    except Exception as e:
        error_msg = f"获取 ARP 表异常: {e}"
        print(f"[IPMAC] {error_msg}")
        task.last_error = error_msg
        task.status = 'failed'
        db.session.commit()
        return
    # 核心 MAC 表（支持 OID 回退）
    try:
        core_mac_table = get_mac_table(core_ip, core_community)
        print(f"[IPMAC] 核心 MAC 表条目数: {len(core_mac_table)}")
    except Exception as e:
        error_msg = f"获取核心 MAC 表异常: {e}"
        print(f"[IPMAC] {error_msg}")
        task.last_error = error_msg
        task.status = 'failed'
        db.session.commit()
        return

    # dot1dBasePort -> ifIndex
    try:
        dot1d_to_ifindex = get_dot1d_base_port_ifindex(core_ip, core_community)
    except Exception as e:
        error_msg = f"获取 dot1dBasePort 映射异常: {e}"
        print(f"[IPMAC] {error_msg}")
        task.last_error = error_msg
        task.status = 'failed'
        db.session.commit()
        return

    # 核心接口映射
    try:
        core_interfaces = discover_interfaces_via_snmp(core_ip, core_community)
        core_port_map = {iface['index']: iface['name'] for iface in core_interfaces}
    except Exception as e:
        error_msg = f"获取核心接口映射异常: {e}"
        print(f"[IPMAC] {error_msg}")
        task.last_error = error_msg
        task.status = 'failed'
        db.session.commit()
        return

    # ---- 核心端口分类：真级联口 vs 虚拟化宿主机上行口 ----
    core_port_mac_lists = defaultdict(list)
    for mac, dot1d_port in core_mac_table.items():
        if_index = dot1d_to_ifindex.get(dot1d_port)
        if if_index:
            core_port_mac_lists[if_index].append(mac)

    core_cascade_ports = set()
    core_vm_skip_macs = set()      # 虚拟网卡 MAC，不参与建链
    core_hypervisor_ports = {}     # if_index -> platform
    for if_index, macs in core_port_mac_lists.items():
        info = classify_port_macs(macs)
        if info['class'] == 'switch_cascade':
            core_cascade_ports.add(if_index)
            port_name = core_port_map.get(if_index, f"Index-{if_index}")
            print(f"[IPMAC] 核心端口 {port_name} 上有 {len(macs)} 个非虚拟化 MAC，视为级联/上行口")
        elif info['class'] == 'hypervisor':
            core_vm_skip_macs.update(info['vm_macs'])
            core_hypervisor_ports[if_index] = info['platform']
            port_name = core_port_map.get(if_index, f"Index-{if_index}")
            print(f"[IPMAC] 核心端口 {port_name} 判定为虚拟化宿主机上行口"
                  f"（{info['vm_count']} 个 VM MAC，平台={info['platform'] or 'unknown'}）")

    # 核心非级联端口 MAC 映射（用于有 IP 设备；宿主机口仅保留物理网卡 MAC）
    mac_to_core = {}
    for mac, dot1d_port in core_mac_table.items():
        mac_norm = normalize_mac(mac)
        if_index = dot1d_to_ifindex.get(dot1d_port)
        if not if_index or if_index in core_cascade_ports:
            continue
        if mac_norm in core_vm_skip_macs:
            continue
        port_name = core_port_map.get(if_index, f"Port-{dot1d_port}")
        mac_to_core[mac_norm] = {
            'device_id': core.id,
            'port': port_name,
            'hypervisor': if_index in core_hypervisor_ports,
            'platform': core_hypervisor_ports.get(if_index, ''),
            'vm_count': len(core_port_mac_lists.get(if_index, [])) - 1,
        }
    print(f"[IPMAC] 核心非级联端口 MAC 数量: {len(mac_to_core)}")

    # ==================== 2. 接入交换机处理 ====================
    mac_to_access = {}           # 用于有 IP 设备快速映射（排除级联端口）
    access_devices_info = []     # 存储每个接入交换机的完整信息，供无 IP 处理使用

    core_ip_addr = core.management_ip or core.ip_address

    for aid in access_device_ids:
        access = Device.query.get(aid)
        if not access:
            continue
        access_ip = access.management_ip or access.ip_address
        if access_ip == core_ip_addr:
            print(f"[IPMAC] 跳过接入交换机 {aid}（IP 与核心相同）")
            continue

        access_community = access.snmp_community or 'public'
        try:
            mac_table = get_mac_table(access_ip, access_community)
            filtered_mac_table = {mac: port for mac, port in mac_table.items()
                                  if not mac.startswith(('ff:ff:ff', '01:00:5e', '33:33', '00:00:00'))}
            dot1d_map = get_dot1d_base_port_ifindex(access_ip, access_community)
            ifaces = discover_interfaces_via_snmp(access_ip, access_community)
            access_port_map = {iface['index']: iface['name'] for iface in ifaces}

            # ---- 接入交换机端口分类：真级联口 vs 虚拟化宿主机上行口 ----
            port_mac_lists = defaultdict(list)
            for mac, dot1d_port in filtered_mac_table.items():
                if_index = dot1d_map.get(dot1d_port)
                if if_index:
                    port_mac_lists[if_index].append(mac)

            cascade_ports = set()
            vm_skip_macs = set()
            hypervisor_ports = {}     # if_index -> platform
            for if_index, macs in port_mac_lists.items():
                info = classify_port_macs(macs)
                if info['class'] == 'switch_cascade':
                    cascade_ports.add(if_index)
                    port_name = access_port_map.get(if_index, f"Index-{if_index}")
                    print(f"[IPMAC] 接入交换机 {aid} 端口 {port_name} 上有 {len(macs)} 个非虚拟化 MAC，视为级联/上行口")
                elif info['class'] == 'hypervisor':
                    vm_skip_macs.update(info['vm_macs'])
                    hypervisor_ports[if_index] = info['platform']
                    port_name = access_port_map.get(if_index, f"Index-{if_index}")
                    print(f"[IPMAC] 接入交换机 {aid} 端口 {port_name} 判定为虚拟化宿主机上行口"
                          f"（{info['vm_count']} 个 VM MAC，平台={info['platform'] or 'unknown'}）")

            access_devices_info.append({
                'aid': aid,
                'mac_table': filtered_mac_table,
                'dot1d_map': dot1d_map,
                'port_map': access_port_map,
                'cascade_ports': cascade_ports,
                'vm_skip_macs': vm_skip_macs,
                'hypervisor_ports': hypervisor_ports,
                'port_mac_lists': port_mac_lists,
            })

            # 构建有 IP 设备映射（排除级联端口；宿主机口排除 VM MAC）
            for mac, dot1d_port in filtered_mac_table.items():
                mac_norm = normalize_mac(mac)
                if mac_norm in mac_to_access:
                    continue
                if_index = dot1d_map.get(dot1d_port)
                if not if_index or if_index in cascade_ports:
                    continue
                if mac_norm in vm_skip_macs:
                    continue
                port_name = access_port_map.get(if_index, f"Port-{dot1d_port}")
                mac_to_access[mac_norm] = {
                    'device_id': aid,
                    'port': port_name,
                    'hypervisor': if_index in hypervisor_ports,
                    'platform': hypervisor_ports.get(if_index, ''),
                    'vm_count': len(port_mac_lists.get(if_index, [])) - 1,
                }
                print(f"[IPMAC] 接入交换机 {aid} MAC {mac_norm} -> 端口 {port_name}")

        except Exception as e:
            print(f"[IPMAC] 处理接入交换机 {aid} 异常: {e}")

    # ==================== 3. 生成连接 ====================
    connections = []
    discovered_ips = set()

    # 辅助函数：检查连接是否已存在于数据库
    def is_conn_exists(src_dev_id, src_port, tgt_dev_id, tgt_port):
        return (src_dev_id, src_port, tgt_dev_id, tgt_port) in existing_conns

    # ---- 3.1 有 IP 的设备（ARP）----
    for ip, mac in arp_entries.items():
        if stop_event and stop_event.is_set():
            break
        if not is_valid_target_ip(ip):
            continue

        mac_norm = normalize_mac(mac)
        info = mac_to_access.get(mac_norm) or mac_to_core.get(mac_norm)
        if not info:
            print(f"[IPMAC] MAC {mac_norm} 未找到有效端口，跳过 IP {ip}")
            continue

        src_dev_id = info['device_id']
        src_port = info['port']
        discovered_ips.add(ip)

        # 查找或创建目标设备（使用增强函数，通过 MAC 查找并补充 IP）
        target_device = find_device_by_mac_and_update(mac_norm, ip_address=ip)
        if target_device:
            target_device_id = target_device.id
            # 如果连接已存在于数据库，跳过
            if is_conn_exists(src_dev_id, src_port, target_device_id, 'unknown'):
                print(f"[IPMAC] 连接已存在，跳过: {src_dev_id}:{src_port} -> {target_device_id}")
                continue
        else:
            target_device_id = None

        connections.append({
            'source_device_id': src_dev_id,
            'source_port': src_port,
            'target_ip': ip,
            'target_mac': mac_norm,
            'target_device_id': target_device_id,
            'target_port': 'unknown',
            'protocol': 'ipmac',
            'neighbor_type': 'hypervisor' if info.get('hypervisor') else 'device',
            'hypervisor_platform': info.get('platform', ''),
            'vm_mac_count': info.get('vm_count', 0) if info.get('hypervisor') else 0,
        })

    # ---- 3.2 无 IP 的设备（MAC 表中未被 ARP 覆盖的 MAC）----
    # ARP 返回的 MAC 已是 12 位 hex 格式，用 normalize_mac 保证一致
    matched_macs = {normalize_mac(mac) for ip, mac in arp_entries.items()}

    # 核心交换机上的无 IP MAC（已排除级联端口）
    for mac, dot1d_port in core_mac_table.items():
        mac_norm = normalize_mac(mac)
        if mac_norm in matched_macs:
            continue
        if_index = dot1d_to_ifindex.get(dot1d_port)
        if not if_index or if_index in core_cascade_ports:
            continue
        if mac_norm in core_vm_skip_macs:
            continue
        port_name = core_port_map.get(if_index, f"Port-{dot1d_port}")
        src_dev_id = core.id
        src_port = port_name

        # 检查源端口是否已被占用（任何连接）
        occupied = ConnectionPath.query.filter(
            ((ConnectionPath.source_device_id == src_dev_id) & (ConnectionPath.source_port == src_port)) |
            ((ConnectionPath.target_device_id == src_dev_id) & (ConnectionPath.target_port == src_port))
        ).first()
        if occupied:
            print(f"[IPMAC] 核心端口 {src_dev_id}:{src_port} 已被占用，跳过无 IP 终端 {mac_norm}")
            continue

        # 查找数据库中的设备（使用增强函数）
        existing_device = find_device_by_mac_and_update(mac_norm)
        target_device_id = existing_device.id if existing_device else None
        target_port = 'unknown'

        if existing_device:
            print(f"[IPMAC] 通过 MAC {mac_norm} 复用已有设备: {existing_device.name}")
            if existing_device.management_ip:
                print(f"[IPMAC] 尝试 SNMP 查询 {existing_device.management_ip} 上的端口")
                remote_iface = get_interface_by_mac_on_device(
                    existing_device.management_ip, mac_norm,
                    existing_device.snmp_community or 'public'
                )
                if remote_iface:
                    target_port = remote_iface
                    print(f"[IPMAC] 获取到对端端口: {remote_iface}")
                else:
                    print(f"[IPMAC] SNMP 查询未返回端口，保持 unknown")
            else:
                print(f"[IPMAC] 设备 {existing_device.name} 无管理 IP，无法获取端口")
        else:
            print(f"[IPMAC] MAC {mac_norm} 不在数据库中，将新建设备")

        connections.append({
            'source_device_id': src_dev_id,
            'source_port': src_port,
            'target_ip': None,
            'target_mac': mac_norm,
            'target_device_id': target_device_id,
            'target_port': target_port,
            'protocol': 'ipmac_no_ip',
            'neighbor_type': 'hypervisor' if if_index in core_hypervisor_ports else 'device',
            'hypervisor_platform': core_hypervisor_ports.get(if_index, ''),
            'vm_mac_count': max(len(core_port_mac_lists.get(if_index, [])) - 1, 0)
                            if if_index in core_hypervisor_ports else 0,
        })
        print(f"[IPMAC] 发现无 IP 终端: MAC {mac_norm} 接在核心端口 {port_name}")

    # 接入交换机上的无 IP MAC（排除级联端口）
    for item in access_devices_info:
        aid = item['aid']
        mac_table = item['mac_table']
        dot1d_map = item['dot1d_map']
        port_map = item['port_map']
        cascade_ports = item['cascade_ports']
        vm_skip_macs = item['vm_skip_macs']
        hypervisor_ports = item['hypervisor_ports']
        port_mac_lists = item['port_mac_lists']
        for mac, dot1d_port in mac_table.items():
            mac_norm = normalize_mac(mac)
            if mac_norm in matched_macs:
                continue
            if_index = dot1d_map.get(dot1d_port)
            if not if_index or if_index in cascade_ports:
                continue
            if mac_norm in vm_skip_macs:
                continue
            port_name = port_map.get(if_index, f"Port-{dot1d_port}")
            src_dev_id = aid
            src_port = port_name

            # 检查源端口是否已被占用
            occupied = ConnectionPath.query.filter(
                ((ConnectionPath.source_device_id == src_dev_id) & (ConnectionPath.source_port == src_port)) |
                ((ConnectionPath.target_device_id == src_dev_id) & (ConnectionPath.target_port == src_port))
            ).first()
            if occupied:
                print(f"[IPMAC] 接入交换机端口 {src_dev_id}:{src_port} 已被占用，跳过无 IP 终端 {mac_norm}")
                continue

            # 通过 MAC 查找数据库中已有的设备（使用增强函数）
            existing_device = find_device_by_mac_and_update(mac_norm)
            target_device_id = existing_device.id if existing_device else None
            target_port = 'unknown'

            if existing_device:
                print(f"[IPMAC] 通过 MAC {mac_norm} 复用已有设备: {existing_device.name}")
                # 如果有管理 IP，尝试 SNMP 获取对端端口
                if existing_device.management_ip:
                    remote_iface = get_interface_by_mac_on_device(
                        existing_device.management_ip,
                        mac_norm,
                        existing_device.snmp_community or 'public',
                        timeout=5
                    )
                    if remote_iface:
                        target_port = remote_iface
                        print(f"[IPMAC] 获取到对端端口: {remote_iface}")
                    else:
                        print(f"[IPMAC] 无法通过 SNMP 获取端口（可能超时或无响应）")
                else:
                    print(f"[IPMAC] 设备无管理 IP，无法获取端口")
            else:
                print(f"[IPMAC] MAC {mac_norm} 不在数据库中，将新建设备")

            connections.append({
                'source_device_id': src_dev_id,
                'source_port': src_port,
                'target_ip': None,
                'target_mac': mac_norm,
                'target_device_id': target_device_id,
                'target_port': target_port,
                'protocol': 'ipmac_no_ip',
                'neighbor_type': 'hypervisor' if if_index in hypervisor_ports else 'device',
                'hypervisor_platform': hypervisor_ports.get(if_index, ''),
                'vm_mac_count': max(len(port_mac_lists.get(if_index, [])) - 1, 0)
                                if if_index in hypervisor_ports else 0,
            })
            print(f"[IPMAC] 发现无 IP 终端: MAC {mac_norm} 接在接入交换机 {aid} 端口 {port_name}")

    # 去重（基于内存中的本次扫描）
    unique_connections = []
    seen = set()
    for conn in connections:
        key = (conn['source_device_id'], conn['source_port'], conn.get('target_mac') or conn.get('target_ip'))
        if key not in seen:
            seen.add(key)
            unique_connections.append(conn)
    connections = unique_connections

    print(f"[IPMAC] 共生成 {len(connections)} 个连接（含无 IP）")

    # ==================== 4. 保存连接 ====================
    if connections:
        try:
            save_ipmac_results(task.id, connections, discovered_ips)
            print("[IPMAC] 结果保存成功")
        except Exception as e:
            print(f"[IPMAC] 保存结果异常: {e}")
            task.last_error = f"保存结果失败: {e}"
            task.status = 'failed'
            db.session.commit()
            return
    else:
        print("[IPMAC] 无连接需要保存")

    # ==================== 5. 【新增】后处理：为有 MAC 无 IP 的设备补充管理 IP ====================

    print("[IPMAC] ========== 开始后处理：为有 MAC 无 IP 的设备补充管理 IP ==========")

    # 构建 ARP 表的 MAC -> IP 映射（标准化后）
    arp_mac_to_ip = {}
    arp_mac_to_ip_raw = {}  # 保留原始格式用于调试

    for ip, mac in arp_entries.items():
        # 标准化 MAC
        mac_norm = normalize_mac(mac)
        if mac_norm and is_valid_target_ip(ip):
            arp_mac_to_ip[mac_norm] = ip
            arp_mac_to_ip_raw[mac] = ip

    print(f"[IPMAC] ARP 表共有 {len(arp_mac_to_ip)} 条有效 MAC->IP 映射")
    for mac_norm, ip in arp_mac_to_ip.items():
        print(f"[IPMAC] ARP: {mac_norm} -> {ip}")

    # 查询所有有 MAC 地址但没有管理 IP 的设备
    devices_without_ip = Device.query.filter(
        Device.mac_address.isnot(None),
        Device.mac_address != '',
        db.or_(
            Device.management_ip.is_(None),
            Device.management_ip == '',
            Device.ip_address.is_(None),
            Device.ip_address == ''
        )
    ).all()

    print(f"[IPMAC] 发现 {len(devices_without_ip)} 个有 MAC 但无管理 IP 的设备")

    updated_count = 0
    for device in devices_without_ip:
        # 获取设备的 MAC 地址（原始格式）
        dev_mac_raw = device.mac_address or ''
        dev_mac_norm = normalize_mac(dev_mac_raw)
        
        print(f"[IPMAC] 检查设备: {device.name}")
        print(f"[IPMAC]   MAC原始: {dev_mac_raw}")
        print(f"[IPMAC]   MAC标准化: {dev_mac_norm}")
        
        if not dev_mac_norm:
            print(f"[IPMAC]   ❌ MAC 标准化失败")
            continue
        
        # 方法1：直接匹配标准化后的 MAC
        if dev_mac_norm in arp_mac_to_ip:
            ip = arp_mac_to_ip[dev_mac_norm]
            device.management_ip = ip
            device.ip_address = ip
            device.updated_at = datetime.now(timezone.utc)
            updated_count += 1
            print(f"[IPMAC]   ✅ 为设备 {device.name} 补充管理 IP: {ip}")
            continue
        
        # 方法2：尝试不同的 MAC 格式变体
        mac_variants = [
            dev_mac_raw.replace(':', '').replace('-', '').lower(),           # 00e04c3e0c70
            dev_mac_raw.replace(':', '-').lower(),                           # 00e0-4c3e-0c70
            dev_mac_raw.replace('-', ':').lower(),                           # 00:e0:4c:3e:0c:70
            dev_mac_raw.upper().replace(':', '-'),                           # 00E0-4C3E-0C70
            dev_mac_norm,                                                   # 标准化的
            dev_mac_norm.lstrip('0'),                                       # 去掉前导0: e04c3e0c70
            dev_mac_norm.zfill(12),                                         # 补前导0
        ]
        
        # 去重
        mac_variants = list(dict.fromkeys(mac_variants))
        
        found = False
        for variant in mac_variants:
            variant_norm = normalize_mac(variant)
            if variant_norm and variant_norm in arp_mac_to_ip:
                ip = arp_mac_to_ip[variant_norm]
                device.management_ip = ip
                device.ip_address = ip
                device.updated_at = datetime.now(timezone.utc)
                updated_count += 1
                found = True
                print(f"[IPMAC]   ✅ 为设备 {device.name} 通过变体匹配补充管理 IP: {ip}")
                print(f"[IPMAC]      匹配变体: {variant} -> {variant_norm}")
                break
        
        if not found:
            # 打印更多调试信息
            print(f"[IPMAC]   ❌ 设备 {device.name} 未在 ARP 表中找到对应 IP")
            print(f"[IPMAC]      尝试的变体: {mac_variants[:5]}...")
            print(f"[IPMAC]      ARP 表中的 MAC 列表: {list(arp_mac_to_ip.keys())}")

    if updated_count > 0:
        db.session.commit()
        print(f"[IPMAC] 后处理完成，共为 {updated_count} 个设备补充了管理 IP")
    else:
        print("[IPMAC] 后处理完成，没有需要补充 IP 的设备")

    
    # ==================== 6. 更新任务统计 ====================
    task.discovered_count = len(discovered_ips)
    task.connection_count = len([c for c in connections if c.get('target_ip')])
    db.session.commit()
    print("[IPMAC] 任务完成")


def _mark_stale_lldp_links(lldp_seen_ips, touched):
    """把本次 LLDP 扫描未再发现、但库里仍存在的 LLDP 链路标记为 down。

    只处理 discovered_by/discovery_protocol 为 lldp 的链路；只处理至少一端属于
    “本次成功读到 LLDP 表”的设备，避免扫描范围不完整或 SNMP 失败时误伤。
    只标记不删除，保留拓扑历史，由链路监控/人工决定后续处理。
    返回本次新标记为 down 的条数。
    """
    from models.models import db, Device, ConnectionPath
    from datetime import datetime, timezone

    if not lldp_seen_ips:
        return 0
    scanned_devs = Device.query.filter(
        db.or_(
            Device.management_ip.in_(lldp_seen_ips),
            Device.ip_address.in_(lldp_seen_ips),
        )
    ).all()
    scanned_ids = {d.id for d in scanned_devs}
    if not scanned_ids:
        return 0

    touched_ids = {c.id for c in touched}
    candidates = ConnectionPath.query.filter(
        db.or_(
            ConnectionPath.discovered_by == 'lldp',
            ConnectionPath.discovery_protocol == 'lldp',
        ),
        db.or_(
            ConnectionPath.source_device_id.in_(scanned_ids),
            ConnectionPath.target_device_id.in_(scanned_ids),
        ),
    ).all()

    now = datetime.now(timezone.utc)
    pruned = 0
    from models.models import Interface
    from utils.link_integrity import derive_link_status
    _iface_cache = {}
    for cp in candidates:
        if cp.id in touched_ids:
            # 本次仍可见：确保为 active
            if cp.link_status != 'active':
                cp.link_status = 'active'
                cp.updated_at = now
            continue
        # 未再发现 ≠ 链路断开：先按两端接口真实状态判定，接口仍 up 则只降置信度，
        # 避免"端口 up/up 却显示断开"（界面状态口径以接口状态为准）
        if cp.source_interface_id and cp.source_interface_id not in _iface_cache:
            _iface_cache[cp.source_interface_id] = Interface.query.get(cp.source_interface_id)
        if cp.target_interface_id and cp.target_interface_id not in _iface_cache:
            _iface_cache[cp.target_interface_id] = Interface.query.get(cp.target_interface_id)
        real = derive_link_status(_iface_cache.get(cp.source_interface_id),
                                  _iface_cache.get(cp.target_interface_id))
        if real == 'active':
            cp.confidence = min(cp.confidence or 0, 60)
            cp.description = ((cp.description or '') +
                              ' 本次扫描未见 LLDP 邻居，但接口状态为 up，保留 active').strip()
            cp.updated_at = now
            continue
        if cp.link_status != 'down':
            cp.link_status = 'down'
            cp.updated_at = now
            pruned += 1
            print(f"[保存] LLDP 链路本次未再发现，标记 down (id={cp.id}): "
                  f"{cp.source_device_id}:{cp.source_port} <-> "
                  f"{cp.target_device_id}:{cp.target_port}")
    return pruned


def save_discovery_results(task_id, connections, discovered_ips, lldp_seen_ips=None):
    """
    保存发现结果到数据库 - 使用统一设备服务
    只保存有IP或MAC地址的设备
    自动通过 SNMP 检测 trunk 端口模式。
    """
    from services.device_service import find_or_create_device, normalize_mac
    from models.models import db, Device, Interface, ConnectionPath
    from datetime import datetime, timezone
    from utils.snmp_utils import snmp_detect_trunk_ports
    import re

    # 预加载设备索引，避免保存阶段逐条查库
    device_index = DeviceIndex()
    device_index.load()

    # 预加载现有连接，供内存去重
    all_conns = ConnectionPath.query.all()
    conn_by_pair = {}
    conns_by_device = defaultdict(list)
    conns_by_endpoint = defaultdict(list)
    for _c in all_conns:
        _pair = (min(_c.source_device_id, _c.target_device_id), max(_c.source_device_id, _c.target_device_id))
        conn_by_pair.setdefault(_pair, _c)
        conns_by_device[_c.source_device_id].append(_c)
        conns_by_device[_c.target_device_id].append(_c)
        if _c.source_port and _c.source_port != 'unknown':
            conns_by_endpoint[(_c.source_device_id, _c.source_port)].append(_c)
        if _c.target_port and _c.target_port != 'unknown':
            conns_by_endpoint[(_c.target_device_id, _c.target_port)].append(_c)

    # ========== 预扫描：对每个源设备查询 trunk 端口 ==========
    trunk_port_cache = {}  # {device_id: {port_name: True}}
    src_ips_seen = set()
    for conn in (connections or []):
        _src_ip = conn.get('source_ip')
        if _src_ip and _src_ip not in src_ips_seen:
            src_ips_seen.add(_src_ip)

    # 查询数据库中这些 IP 对应的设备
    for ip in src_ips_seen:
        dev = device_index.by_ip_get(ip)
        if dev and dev.id not in trunk_port_cache:
            community = getattr(dev, 'snmp_community', None) or 'public'
            version = str(getattr(dev, 'snmp_version', '2c') or '2c')
            try:
                trunk_ports = snmp_detect_trunk_ports(ip, community, version, timeout=3)
                if trunk_ports:
                    trunk_port_cache[dev.id] = trunk_ports
                    print(f"[保存] 设备 {dev.name} 检测到 {len(trunk_ports)} 个 trunk 端口: {list(trunk_ports.keys())}")
            except Exception as e:
                print(f"[保存] trunk 检测失败 {dev.name} ({ip}): {e}")

    if not connections:
        print("[保存] 没有连接需要保存")
        return

    print(f"[保存] 开始保存发现结果，任务ID={task_id}")
    print(f"[保存] 总共发现 {len(connections)} 个连接")

    saved_count = 0
    skipped_no_id = 0
    touched = set()   # 本次扫描中确认仍存在的连接行，用于过期 LLDP 链路清理
    
    for conn in connections:
        src_ip = conn.get('source_ip')
        src_port = conn.get('source_port', 'unknown')
        tgt_ip = conn.get('target_ip')
        tgt_port = conn.get('target_port', 'unknown')
        protocol = conn.get('protocol', 'unknown')
        remote_sysname = conn.get('remote_sysname', '')
        remote_chassis = conn.get('remote_chassis', '')
        remote_mac = conn.get('remote_mac', '') or conn.get('remote_chassis', '')
        # 端口描述（interface description，如 TO-ShouShuShi），与端口名分离，单独写入 Interface.description
        source_port_desc = conn.get('source_port_desc', '') or ''
        target_port_desc = conn.get('target_port_desc', '') or ''

        if not src_ip:
            print(f"[保存] 跳过：源IP为空")
            continue

        # 1. 获取源设备（优先使用预解析的 source_device_id）
        src_dev = None
        src_device_id = conn.get('source_device_id')
        if src_device_id:
            src_dev = device_index.by_id_get(src_device_id)
            if src_dev:
                print(f"[保存] 使用预解析的源设备: {src_dev.name} (ID={src_device_id})")
        if not src_dev:
            src_dev = device_index.by_ip_get(src_ip)
        if not src_dev:
            print(f"[保存] 源设备 {src_ip} 不存在，跳过（请确认设备已在数据库内，或先通过IP/MAC发现建立设备）")
            continue

        # ===== 检查目标设备是否已有预解析的 device_id =====
        pre_resolved_device_id = conn.get('target_device_id')
        tgt_dev = None

        if pre_resolved_device_id:
            tgt_dev = device_index.by_id_get(pre_resolved_device_id)
            if tgt_dev:
                print(f"[保存] 使用预解析的目标设备: {tgt_dev.name} (ID={pre_resolved_device_id})")
            else:
                print(f"[保存] 预解析设备ID={pre_resolved_device_id} 无效，回退到IP/MAC查找")

        # ===== 检查目标设备是否有 IP 或 MAC =====
        has_ip = tgt_ip and is_valid_target_ip(tgt_ip)
        mac_clean = remote_mac.replace(':', '').replace('-', '').lower()
        has_mac = mac_clean and len(mac_clean) == 12

        if not tgt_dev and not has_ip and not has_mac:
            print(f"[保存] 跳过：目标设备无IP、无MAC、无预解析ID - {conn}")
            skipped_no_id += 1
            continue

        # ========== 2. 使用统一服务获取或创建目标设备 ==========
        if not tgt_dev:
            # 确定设备名称
            dev_name = None
            if remote_sysname and remote_sysname != 'unknown':
                dev_name = remote_sysname
            elif tgt_ip and is_valid_target_ip(tgt_ip):
                dev_name = f"Device-{tgt_ip.replace('.', '_')}"

            # 使用统一服务
            tgt_dev = find_or_create_device(
                ip=tgt_ip if has_ip else None,
                mac=remote_mac if has_mac else None,
                name=dev_name,
                hostname=remote_sysname if remote_sysname else None,
                device_type='unknown',
                snmp_community='public',
                status='unknown'
            )

            if not tgt_dev:
                print(f"[保存] 创建目标设备失败，跳过")
                continue

        # ===== 2.4 宿主机标记：MAC 表识别到大量 VM MAC / LLDP 识别到虚拟化平台 =====
        neighbor_type = conn.get('neighbor_type', '')
        platform = conn.get('hypervisor_platform', '') or ''
        vm_count = conn.get('vm_mac_count', 0) or 0
        if neighbor_type == 'hypervisor' or platform or vm_count > 0:
            marked = False
            if not tgt_dev.is_virtual_host:
                tgt_dev.is_virtual_host = True
                marked = True
            if platform and (not tgt_dev.virtualization_type or tgt_dev.virtualization_type in ('', 'other')):
                tgt_dev.virtualization_type = platform
                marked = True
            if marked:
                print(f"[保存] 标记 {tgt_dev.name} 为虚拟化宿主机"
                      f"（neighbor_type={neighbor_type}, platform={platform or '-'}, vm_mac_count={vm_count}）")

        # ========== 2.5 端口名验证：过滤/修正非物理端口名（方向归一化之前） ==========
        # r01 的 Cellular0/0、Aux0、NULL0 等是虚拟/逻辑接口，不连物理设备
        # 必须在归一化之前校验，这样才能正确追踪哪台设备的端口有问题
        port_invalid_skip = False
        for _side, _port, _dev in [('source', src_port, src_dev), ('target', tgt_port, tgt_dev)]:
            if is_non_physical_port(_port):
                _dev_ip = _dev.management_ip or _dev.ip_address
                _community = getattr(_dev, 'snmp_community', None) or 'public'
                real_port, fix_source = find_real_physical_port(
                    _dev.id, _dev_ip, _community, _port
                )
                if real_port:
                    print(f"[保存] {_dev.name} 非物理端口 '{_port}' → 修正为 '{real_port}' (来源: {fix_source})")
                    if _side == 'source':
                        src_port = real_port
                    else:
                        tgt_port = real_port
                else:
                    print(f"[保存] ⚠️ {_dev.name} 端口 '{_port}' 为非物理端口且无法修正，跳过此链路")
                    port_invalid_skip = True
                    break

        if port_invalid_skip:
            continue

        # ========== 3. 去重：链路双向归一化 ==========
        # 物理链路 A--B 只应存一条，不管扫描方向是谁→谁
        # 固定规则：较小的 device_id 放 source，确保每对设备只产生一条记录
        # 必须在端口占用检查之前执行，否则归一化后 src_dev/src_port 变化导致检查失效
        if src_dev.id > tgt_dev.id:
            # 交换方向，使小 ID 为 source
            src_dev, tgt_dev = tgt_dev, src_dev
            src_port, tgt_port = tgt_port, src_port
            # 端口描述随方向一并交换，保持与端口名一致
            source_port_desc, target_port_desc = target_port_desc, source_port_desc

        # ========== 4. 端口冲突统一交给 4e 按协议优先级处理，这里不再简单跳过 ==========

        existing = conn_by_pair.get((min(src_dev.id, tgt_dev.id), max(src_dev.id, tgt_dev.id)))
        if existing:
            touched.add(existing)
            # 已有链路，仅更新端口 / 协议 / 状态（如果新数据更精确）
            updated = False
            if tgt_port and existing.target_port in ('unknown', ''):
                existing.target_port = tgt_port
                updated = True
            if src_port and existing.source_port in ('unknown', ''):
                existing.source_port = src_port
                updated = True
            if protocol and protocol != 'unknown' and existing.discovered_by == 'unknown':
                existing.discovered_by = protocol
                updated = True
            if existing.link_status != 'active':
                existing.link_status = 'active'
                updated = True
            existing.updated_at = datetime.now(timezone.utc)
            if updated:
                db.session.flush()
                print(f"[保存] 更新已有链路: {src_dev.name}:{src_port} ↔ {tgt_dev.name}:{tgt_port}")
            else:
                print(f"[保存] 链路已存在: {src_dev.name}:{src_port} ↔ {tgt_dev.name}:{tgt_port}")
            continue

        # ========== 4b. 目标设备去重：防止上联口产生重复连接 ==========
        # 如果目标设备在其它源设备上已有连接（同一个 MAC 被多个交换机报告），
        # 优先保留非上联口/LLDP 的连接，跳过来自上联口的重复连接
        existing_for_target = None
        for _c in conns_by_device.get(tgt_dev.id, []):
            _other_id = _c.source_device_id if _c.target_device_id == tgt_dev.id else _c.target_device_id
            if _other_id != src_dev.id:
                existing_for_target = _c
                break

        if existing_for_target:
            # 完全跳过：目标设备已被其他设备连接
            # 精确匹配已在上面 (existing) 处理；这里命中的是 (B,A) 反向或 (C,A) 上联口冲突
            other_src_id = (existing_for_target.source_device_id
                            if existing_for_target.source_device_id != tgt_dev.id
                            else existing_for_target.target_device_id)
            other_src = device_index.by_id_get(other_src_id)
            other_src_name = other_src.name if other_src else f"Device#{other_src_id}"

            # 端口是否完全一致（反向也算一致）
            same_pair = (
                (existing_for_target.source_device_id == src_dev.id
                 and existing_for_target.target_device_id == tgt_dev.id
                 and existing_for_target.source_port == src_port
                 and existing_for_target.target_port == tgt_port)
                or
                (existing_for_target.source_device_id == tgt_dev.id
                 and existing_for_target.target_device_id == src_dev.id
                 and existing_for_target.source_port == tgt_port
                 and existing_for_target.target_port == src_port)
            )

            is_existing_lldp = (existing_for_target.discovered_by == 'lldp' or
                               (existing_for_target.discovery_protocol or '') == 'lldp')
            is_new_lldp = (protocol == 'lldp')

            if same_pair:
                # 完全重复（同对设备+同两端端口），直接跳过
                print(f"[保存] 重复连接（同对同端口）: {src_dev.name}:{src_port} ↔ {tgt_dev.name}:{tgt_port}")
                touched.add(existing_for_target)
                continue
            elif is_existing_lldp and not is_new_lldp:
                # 已有 LLDP 连接，跳过 MAC 发现的重复
                print(f"[保存] 目标设备 {tgt_dev.name} 已有 LLDP 连接 ({other_src_name})，跳过 MAC 重复")
                continue
            elif not is_existing_lldp and is_new_lldp:
                # LLDP 连接替换 MAC 连接
                db.session.delete(existing_for_target)
                db.session.flush()
                print(f"[保存] LLDP 连接替换已有 MAC 连接: {tgt_dev.name} (旧: {other_src_name})")
            elif is_existing_lldp and is_new_lldp:
                # 两者都是 LLDP，但源设备不同 → 是不同的物理连接，应保存
                # （同源设备的情况已被上面 existing 检查处理）
                print(f"[保存] 目标设备 {tgt_dev.name} 已有 LLDP 连接 ({other_src_name})，"
                      f"但来自 {src_dev.name} 的连接是不同链路，予以保留")
                # 不 continue，继续往下保存新连接
            else:
                # 两者都不是 LLDP（如都是 SNMP MAC 或 IPMAC），保留第一条连接
                print(f"[保存] 目标设备 {tgt_dev.name} 已有连接 ({other_src_name})，跳过来自 {src_dev.name} 的重复")
                continue

        # ========== 4c. 端口名归一：MAC 不能当端口名（未识别设备常以 MAC 建接口）==========
        from utils.link_integrity import looks_like_mac
        _mac_notes = []
        if looks_like_mac(src_port):
            _mac_notes.append(f"源端口未识别(原值 {src_port})")
            src_port = 'unknown'
        if looks_like_mac(tgt_port):
            _mac_notes.append(f"目标端口未识别(原值 {tgt_port})")
            tgt_port = 'unknown'

        # 确保源接口存在
        src_iface = None
        if src_port != 'unknown':
            src_iface = Interface.query.filter_by(device_id=src_dev.id, name=src_port).first()
        if not src_iface and src_port != 'unknown':
            src_iface = Interface(
                device_id=src_dev.id,
                name=src_port,
                description=source_port_desc or None,
                type='unknown',
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.session.add(src_iface)
            db.session.flush()
        elif source_port_desc and src_iface.description != source_port_desc:
            src_iface.description = source_port_desc
            src_iface.updated_at = datetime.now(timezone.utc)

        # 目标接口
        tgt_iface = None
        if tgt_port != 'unknown':
            tgt_iface = Interface.query.filter_by(device_id=tgt_dev.id, name=tgt_port).first()
            if not tgt_iface:
                tgt_iface = Interface(
                    device_id=tgt_dev.id,
                    name=tgt_port,
                    description=target_port_desc or None,
                    type='unknown',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.session.add(tgt_iface)
                db.session.flush()
            elif target_port_desc and tgt_iface.description != target_port_desc:
                tgt_iface.description = target_port_desc
                tgt_iface.updated_at = datetime.now(timezone.utc)

        # ========== 判断连接类型：检查是否为 trunk 端口 ==========
        determined_type = 'physical'
        src_trunks = trunk_port_cache.get(src_dev.id, {})
        tgt_trunks = trunk_port_cache.get(tgt_dev.id, {})
        if (src_port in src_trunks) or (tgt_port in tgt_trunks):
            determined_type = 'trunk'
            print(f"[保存] 检测到 trunk 端口: {src_dev.name}:{src_port}(trunk={src_port in src_trunks}) ↔ {tgt_dev.name}:{tgt_port}(trunk={tgt_port in tgt_trunks})")

        # ========== 4e. 端口占用护栏：一个物理口只能有一个对端 ==========
        # 精确去重（同对设备+同端口）已在上面处理；这里拦截"同端口、不同对端"的情形
        # （多因设备改接后旧 LLDP 记录未老化），以本次发现为准更新旧记录而非再建一条。
        if src_port != 'unknown' or tgt_port != 'unknown':
            _occupied = None
            for _ep in ((src_dev.id, src_port), (tgt_dev.id, tgt_port)):
                if not _ep[1] or _ep[1] == 'unknown':
                    continue
                for _c in conns_by_endpoint.get(_ep, []):
                    if _c not in touched:
                        _occupied = _c
                        break
                if _occupied:
                    break
            if _occupied and _occupied not in touched:
                _same = ((_occupied.source_device_id == src_dev.id
                          and _occupied.target_device_id == tgt_dev.id)
                         or (_occupied.source_device_id == tgt_dev.id
                             and _occupied.target_device_id == src_dev.id))
                if not _same:
                    _old_proto = (_occupied.discovered_by or _occupied.discovery_protocol or 'unknown')
                    _old_pri = PROTOCOL_PRIORITY.get(str(_old_proto), 0)
                    _new_pri = PROTOCOL_PRIORITY.get(str(protocol), 0)
                    if _new_pri < _old_pri:
                        print(f"[保存] 端口已被连接 #{_occupied.id} 占用，且旧协议优先级更高({_old_proto})，跳过本次")
                        continue
                    print(f"[保存] 端口已被连接 #{_occupied.id} 占用，按本次发现更新对端: "
                          f"{src_dev.name}:{src_port} ↔ {tgt_dev.name}:{tgt_port}")
                    _occupied.source_device_id = src_dev.id
                    _occupied.source_port = src_port
                    _occupied.source_interface_id = src_iface.id if src_iface else None
                    _occupied.target_device_id = tgt_dev.id
                    _occupied.target_port = tgt_port
                    _occupied.target_interface_id = tgt_iface.id if tgt_iface else None
                    _occupied.discovery_time = datetime.now(timezone.utc)
                    _occupied.last_seen = datetime.now(timezone.utc)
                    _occupied.updated_at = datetime.now(timezone.utc)
                    _occupied.link_status = 'active'
                    touched.add(_occupied)
                    db.session.flush()
                    continue

        # 创建新连接
        new_conn = ConnectionPath(
            source_device_id=src_dev.id,
            source_interface_id=src_iface.id if src_iface else None,
            source_port=src_port,
            target_device_id=tgt_dev.id,
            target_interface_id=tgt_iface.id if tgt_iface else None,
            target_port=tgt_port,
            discovered_by=protocol,
            discovery_protocol=protocol,
            connection_type=determined_type,
            link_status='active',
            confidence=100,
            discovery_time=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        if _mac_notes:
            new_conn.description = '；'.join(_mac_notes)
            new_conn.confidence = 70
        db.session.add(new_conn)
        db.session.flush()
        saved_count += 1
        touched.add(new_conn)
        print(f"[保存] 创建新连接: {src_dev.name}:{src_port} ↔ {tgt_dev.name}:{tgt_port} (IP: {tgt_ip}, MAC: {remote_mac})")

    # ========== 清理过期 LLDP 链路（标记 down，不删除） ==========
    try:
        pruned = _mark_stale_lldp_links(lldp_seen_ips or set(), touched)
        if pruned:
            print(f"[保存] 共 {pruned} 条 LLDP 链路因本次未再发现被标记为 down")
    except Exception as e:
        print(f"[保存] LLDP 过期链路清理失败: {e}")
        import traceback
        traceback.print_exc()

    try:
        db.session.commit()
        print(f"[保存] 保存完成，共保存 {saved_count} 条连接，跳过 {skipped_no_id} 条无标识设备")
    except Exception as e:
        db.session.rollback()
        print(f"[保存] 保存失败: {e}")
        import traceback
        traceback.print_exc()

def save_ipmac_results(task_id, connections, discovered_ips):
    """
    保存 IP/MAC 发现的连接结果到 ConnectionPath 表。
    connections: 列表，每个元素包含：
        source_device_id, source_port, target_device_id, target_ip, target_mac, target_port, protocol
    自动通过 SNMP 检测 trunk 端口模式。
    """
    from models.models import Device, ConnectionPath, db
    from utils.snmp_utils import snmp_detect_trunk_ports

    # 预加载设备索引，避免保存阶段逐条查库
    device_index = DeviceIndex()
    device_index.load()

    # 预加载现有连接，供内存去重
    all_conns = ConnectionPath.query.all()
    conn_by_pair = {}
    conns_by_device = defaultdict(list)
    conns_by_endpoint = defaultdict(list)
    for _c in all_conns:
        _pair = (min(_c.source_device_id, _c.target_device_id), max(_c.source_device_id, _c.target_device_id))
        conn_by_pair.setdefault(_pair, _c)
        conns_by_device[_c.source_device_id].append(_c)
        conns_by_device[_c.target_device_id].append(_c)
        if _c.source_port and _c.source_port != 'unknown':
            conns_by_endpoint[(_c.source_device_id, _c.source_port)].append(_c)
        if _c.target_port and _c.target_port != 'unknown':
            conns_by_endpoint[(_c.target_device_id, _c.target_port)].append(_c)

    # ========== 预扫描：对每个源设备查询 trunk 端口 ==========
    trunk_port_cache = {}  # {device_id: {port_name: True}}
    src_dev_ids_seen = set()
    for conn in (connections or []):
        _src_id = conn.get('source_device_id')
        if _src_id and _src_id not in src_dev_ids_seen:
            src_dev_ids_seen.add(_src_id)

    for dev_id in src_dev_ids_seen:
        dev = device_index.by_id_get(dev_id)
        if dev:
            ip = dev.management_ip or dev.ip_address
            if ip:
                community = getattr(dev, 'snmp_community', None) or 'public'
                version = str(getattr(dev, 'snmp_version', '2c') or '2c')
                try:
                    trunk_ports = snmp_detect_trunk_ports(ip, community, version, timeout=3)
                    if trunk_ports:
                        trunk_port_cache[dev_id] = trunk_ports
                        print(f"[IPMAC] 设备 {dev.name} 检测到 {len(trunk_ports)} 个 trunk 端口")
                except Exception as e:
                    print(f"[IPMAC] trunk 检测失败 {dev.name} ({ip}): {e}")

    saved_count = 0
    for conn in connections:
        # 1. 确定目标设备 ID（优先使用已经查到的 target_device_id）
        target_device_id = conn.get('target_device_id')
        
        # 如果没有 target_device_id，尝试按 IP 或 MAC 查找/创建设备（兜底逻辑）
        if not target_device_id:
            if conn.get('target_ip'):
                target_device = device_index.by_ip_get(conn['target_ip'])
                if not target_device:
                    target_device = Device(
                        name=f"Device-{conn['target_ip'].replace('.', '_')}",
                        management_ip=conn['target_ip'],
                        device_type='terminal',
                        status='active',
                        mac_address=conn.get('target_mac')
                    )
                    db.session.add(target_device)
                    db.session.flush()
                target_device_id = target_device.id
            elif conn.get('target_mac'):
                # 仅通过MAC查到已有设备则复用，否则跳过（无确认IP不入库）
                target_device = device_index.by_mac_get(conn['target_mac'])
                if target_device:
                    target_device_id = target_device.id
                    print(f"[IPMAC] 复用已有设备(仅MAC): {target_device.name}")
                else:
                    print(f"[IPMAC] 跳过无IP设备(MAC: {conn['target_mac']}), 未确定IP不入库")
                    continue
            else:
                print(f"[IPMAC] 连接缺少目标标识，跳过: {conn}")
                continue

        # ===== 1.5 宿主机标记：IP/MAC 发现识别到大量 VM MAC 的端口 =====
        if conn.get('neighbor_type') == 'hypervisor' or conn.get('hypervisor_platform'):
            td = device_index.by_id_get(target_device_id)
            if td:
                marked = False
                if not td.is_virtual_host:
                    td.is_virtual_host = True
                    marked = True
                platform = conn.get('hypervisor_platform', '') or ''
                if platform and (not td.virtualization_type or td.virtualization_type in ('', 'other')):
                    td.virtualization_type = platform
                    marked = True
                if marked:
                    print(f"[IPMAC] 标记 {td.name} 为虚拟化宿主机"
                          f"（platform={platform or '-'}, vm_mac_count={conn.get('vm_mac_count', 0)}）")

        # 2. 双向归一化：把较小的 device_id 永远放 source
        src_id = conn['source_device_id']
        src_port = conn['source_port']
        tgt_id = target_device_id
        tgt_port = conn.get('target_port', 'unknown')

        if src_id > tgt_id:
            src_id, tgt_id = tgt_id, src_id
            src_port, tgt_port = tgt_port, src_port

        # 3. 去重：同一个设备对只保留一条链路
        existing = conn_by_pair.get((min(src_id, tgt_id), max(src_id, tgt_id)))

        if existing:
            # 已有链路，仅更新端口（如果新数据更精确）
            updated = False
            if tgt_port and tgt_port != 'unknown' and existing.target_port in ('unknown', ''):
                existing.target_port = tgt_port
                updated = True
            if src_port and src_port != 'unknown' and existing.source_port in ('unknown', ''):
                existing.source_port = src_port
                updated = True
            existing.updated_at = datetime.now(timezone.utc)
            if updated:
                db.session.flush()
                print(f"[IPMAC] 更新已有链路端口: {existing.source_port} ↔ {existing.target_port}")
            else:
                print(f"[IPMAC] 链路已存在，跳过: {src_id}:{src_port} ↔ {tgt_id}:{tgt_port}")
            continue

        # 3b. 端口占用检查：源端口是否已被占用（低优先级不覆盖，高优先级交给后续去重）
        port_occupied = None
        if src_port and src_port != 'unknown':
            for _c in conns_by_endpoint.get((src_id, src_port), []):
                if _c not in touched:
                    port_occupied = _c
                    break
        if port_occupied:
            _same = (port_occupied.source_device_id == src_id and port_occupied.target_device_id == tgt_id) or                     (port_occupied.source_device_id == tgt_id and port_occupied.target_device_id == src_id)
            _old_proto = (port_occupied.discovered_by or port_occupied.discovery_protocol or 'unknown')
            _old_pri = PROTOCOL_PRIORITY.get(str(_old_proto), 0)
            _new_pri = PROTOCOL_PRIORITY.get(str(conn.get('protocol', 'ipmac')), 0)
            if _same:
                touched.add(port_occupied)
                continue
            if _new_pri < _old_pri:
                print(f"[IPMAC] 端口 Device#{src_id}:{src_port} 已被更高优先级链路占用，跳过")
                continue
            # 否则允许后续 existing_for_target 决定，不再在此跳过

        # 3c. 目标设备去重：防止上联口产生重复连接
        # IP/MAC 发现的结果不能和已存在的 LLDP 连接冲突
        existing_for_target = None
        for _c in conns_by_device.get(tgt_id, []):
            _other_id = _c.source_device_id if _c.target_device_id == tgt_id else _c.target_device_id
            if _other_id != src_id:
                existing_for_target = _c
                break

        if existing_for_target:
            # 端口是否完全一致（反向也算一致）
            same_pair = (
                (existing_for_target.source_device_id == src_id
                 and existing_for_target.target_device_id == tgt_id
                 and existing_for_target.source_port == src_port
                 and existing_for_target.target_port == tgt_port)
                or
                (existing_for_target.source_device_id == tgt_id
                 and existing_for_target.target_device_id == src_id
                 and existing_for_target.source_port == tgt_port
                 and existing_for_target.target_port == src_port)
            )
            if same_pair:
                print(f"[IPMAC] 重复连接（同对同端口）: {src_id}:{src_port} ↔ {tgt_id}:{tgt_port}")
                continue
            other_src_id = (existing_for_target.source_device_id
                            if existing_for_target.source_device_id != tgt_id
                            else existing_for_target.target_device_id)
            is_existing_lldp = (existing_for_target.discovered_by == 'lldp' or
                               (existing_for_target.discovery_protocol or '') == 'lldp')
            if is_existing_lldp:
                other_src = Device.query.get(other_src_id)
                other_src_name = other_src.name if other_src else f"Device#{other_src_id}"
                print(f"[IPMAC] 目标设备已有 LLDP 连接 ({other_src_name})，跳过 IPMAC 重复")
                continue

        # ========== 判断连接类型：检查是否为 trunk 端口 ==========
        determined_type = 'physical'
        src_trunks = trunk_port_cache.get(src_id, {})
        tgt_trunks = trunk_port_cache.get(tgt_id, {})
        if (src_port in src_trunks) or (tgt_port in tgt_trunks):
            determined_type = 'trunk'

        # 4. 创建 ConnectionPath 记录（使用归一化后的方向）
        cp = ConnectionPath(
            source_device_id=src_id,
            source_port=src_port,
            target_device_id=tgt_id,
            target_port=tgt_port,
            discovered_by='ipmac',
            discovery_protocol=conn.get('protocol', 'ipmac'),
            connection_type=determined_type,
            link_status='unknown',
            confidence=80,
            discovery_time=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.session.add(cp)
        db.session.flush()
        saved_count += 1

    db.session.commit()
    print(f"[IPMAC] 共保存 {saved_count} 条连接")

def discover_lldp_neighbors(ip: str, community: str = 'public') -> List[Dict[str, Any]]:
    """
    通过 SNMP 发现 LLDP 邻居，自动处理编码（支持中文）
    """
    from utils.utils import snmp_walk
    import re

    # ... 使用上面定义的 decode_snmp_string 和 detect_encoding_and_fix ...

    # ========== 1. 获取 lldpLocPortIfIndex ==========
    local_ifindex_map = {}
    entries = snmp_walk(ip, '1.0.8802.1.1.2.1.3.7.1.2', community, timeout=10, retries=3)
    for oid, val in entries:
        parts = oid.split('.')
        if not parts:
            continue
        lldp_port = parts[-1]
        val_str = decode_snmp_string(val)
        if val_str.isdigit():
            local_ifindex_map[lldp_port] = val_str
        else:
            local_ifindex_map[lldp_port] = str(val)

    # ========== 2. 获取 lldpLocPortDesc ==========
    local_desc_map = {}
    entries = snmp_walk(ip, '1.0.8802.1.1.2.1.3.7.1.4', community, timeout=10, retries=3)
    for oid, val in entries:
        parts = oid.split('.')
        if not parts:
            continue
        lldp_port = parts[-1]
        desc = decode_snmp_string(val)
        desc = re.sub(r'\s+Interface$', '', desc, flags=re.IGNORECASE).strip()
        local_desc_map[lldp_port] = desc

    # ========== 2.5 获取 ifIndex -> ifName 映射（把 Port-{ifIndex} 还原成真实端口名）==========
    ifindex_to_name = {}
    try:
        ifaces = discover_interfaces_via_snmp(ip, community)
        for iface in ifaces:
            idx = str(iface.get('index', '') or '').strip()
            if idx:
                ifindex_to_name[idx] = iface['name']
        if ifindex_to_name:
            print(f"[LLDP] 已构建 ifIndex->ifName 映射: {len(ifindex_to_name)} 条（{ip}）")
    except Exception as e:
        print(f"[LLDP] 获取 ifIndex->ifName 映射失败 ({ip}): {e}")

    # ========== 3. 获取 LLDP Remote 表 ==========
    oid_map = {
        'remote_chassis': '1.0.8802.1.1.2.1.4.1.1.5',
        'remote_port': '1.0.8802.1.1.2.1.4.1.1.7',
        'remote_port_desc': '1.0.8802.1.1.2.1.4.1.1.8',
        'local_port_num': '1.0.8802.1.1.2.1.4.1.1.6',
        'remote_sysname': '1.0.8802.1.1.2.1.4.1.1.9',
        'remote_sysdesc': '1.0.8802.1.1.2.1.4.1.1.10',
        'cap_supported': '1.0.8802.1.1.2.1.4.1.1.11',
        'cap_enabled': '1.0.8802.1.1.2.1.4.1.1.12',
    }

    raw_data = {}
    for key, oid in oid_map.items():
        entries = snmp_walk(ip, oid, community, timeout=10, retries=3)
        for oid_str, val in entries:
            parts = oid_str.split('.')
            if len(parts) < 3:
                continue
            
            time_mark = parts[-3]
            local_port_num = parts[-2]
            remote_index = parts[-1]
            composite_key = (time_mark, local_port_num, remote_index)
            
            if composite_key not in raw_data:
                raw_data[composite_key] = {}
            
            # ===== 关键：使用 decode_snmp_string 处理所有值 =====
            val_str = decode_snmp_string(val)
            
            if "No Such Instance" in val_str or not val_str.strip():
                continue
            
            raw_data[composite_key][key] = val_str

    # ========== 4. 构建邻居列表 ==========
    neighbors = []
    for (time_mark, local_port_num, remote_idx), data in raw_data.items():
        if not local_port_num:
            continue

        local_ifindex = local_ifindex_map.get(local_port_num, '')
        local_desc = local_desc_map.get(local_port_num, '')  # 本地端口描述（interface description）

        # 端口身份统一用真实接口名（ifIndex→ifName）；描述单独上抛到 Interface.description，
        # 避免用描述（如 TO-ShouShuShi）覆盖端口名导致与 Interface.name 对不上、CMDB 关联丢失
        if local_ifindex and local_ifindex in ifindex_to_name:
            local_interface_name = ifindex_to_name[local_ifindex]
        elif local_ifindex:
            local_interface_name = f"Port-{local_ifindex}"
        else:
            local_interface_name = f"Port-{local_port_num}"

        # 远端端口身份用 lldpRemPortId（真实端口名，OID .7）；描述（OID .8）单独保留
        remote_port = (data.get('remote_port', '') or '').strip()
        if not remote_port:
            # 极少数设备 lldpRemPortId 为空时退化用端口描述，最后才 unknown
            remote_port = (data.get('remote_port_desc', '') or '').strip()
        if not remote_port:
            # remote_idx 只是 OID 索引，不是真实端口名，用 unknown 占位而非 Port-{remote_idx}
            remote_port = 'unknown'
        remote_port = re.sub(r'\s+Interface$', '', remote_port, flags=re.IGNORECASE).strip()
        remote_port_desc = (data.get('remote_port_desc', '') or '').strip()

        # ===== 获取远程系统名称（已通过 decode_snmp_string 处理）=====
        remote_sysname = data.get('remote_sysname', '')
        remote_sysdesc = data.get('remote_sysdesc', '')
        remote_chassis = data.get('remote_chassis', '')

        # 额外修复：如果名称以 "STRING:" 开头（兜底）
        if remote_sysname and remote_sysname.startswith('STRING:'):
            remote_sysname = remote_sysname.replace('STRING:', '').strip().strip('"')
        
        # 打印调试信息
        if remote_sysname:
            print(f"[LLDP] 解析邻居: {remote_sysname}")

        neighbor = {
            'local_lldp_port': local_port_num,
            'local_ifindex': local_ifindex,
            'local_interface_name': local_interface_name,
            'local_port_desc': local_desc,
            'remote_idx': remote_idx,
            'remote_chassis': remote_chassis,
            'remote_port': remote_port,
            'remote_port_desc': remote_port_desc,
            'remote_sysname': remote_sysname,
            'remote_sysdesc': remote_sysdesc,
            'cap_supported': data.get('cap_supported', ''),
            'cap_enabled': data.get('cap_enabled', ''),
        }
        neighbors.append(neighbor)

    # ========== 5. 去重 ==========
    unique_neighbors = {}
    for n in neighbors:
        key = (n['local_lldp_port'], n['remote_idx'], n['remote_chassis'])
        if key not in unique_neighbors:
            unique_neighbors[key] = n
        else:
            existing = unique_neighbors[key]
            if n['remote_sysname'] and not existing['remote_sysname']:
                existing['remote_sysname'] = n['remote_sysname']
            if n['remote_port'] and not existing['remote_port']:
                existing['remote_port'] = n['remote_port']
    
    neighbors = list(unique_neighbors.values())

    print(f"[LLDP] 从 {ip} 发现 {len(neighbors)} 个邻居")
    return neighbors

def discover_cdp_neighbors(ip: str, community: str = 'public') -> List[Dict[str, Any]]:
    """
    通过 SNMP 发现 CDP 邻居（Cisco Discovery Protocol）
    使用 CISCO-CDP-MIB (1.3.6.1.4.1.9.9.23)
    返回邻居列表，每个元素包含：
        - local_ifindex: 本地接口 ifIndex
        - local_interface: 本地接口名称（通过 ifIndex 映射，需外部提供）
        - remote_device: 对端设备名称
        - remote_interface: 对端接口名称
        - remote_ip: 对端 IP 地址（如果有）
        - remote_platform: 对端设备平台信息
    """
    # CDP Cache 表 OID 前缀
    print("=============开始cdp发现--==================")
    CDP_CACHE_PREFIX = '1.3.6.1.4.1.9.9.23.1.2.1.1'

    # 子 OID 定义
    CDP_CACHE_IFINDEX = '1.3.6.1.4.1.9.9.23.1.2.1.1.6'   # cdpCacheIfIndex
    CDP_CACHE_DEVICE_ID = '1.3.6.1.4.1.9.9.23.1.2.1.1.6'  # 注意：实际 OID 是 1.3.6.1.4.1.9.9.23.1.2.1.1.6? 需确认
    # 标准 MIB:
    # cdpCacheIfIndex      .1.3.6.1.4.1.9.9.23.1.2.1.1.2
    # cdpCacheDeviceId     .1.3.6.1.4.1.9.9.23.1.2.1.1.6
    # cdpCacheDevicePort   .1.3.6.1.4.1.9.9.23.1.2.1.1.7
    # cdpCachePlatform     .1.3.6.1.4.1.9.9.23.1.2.1.1.8
    # cdpCacheAddressType  .1.3.6.1.4.1.9.9.23.1.2.1.1.4
    # cdpCacheAddress      .1.3.6.1.4.1.9.9.23.1.2.1.1.5

    # 使用正确的 OID（根据 CISCO-CDP-MIB）
    oid_map = {
        'local_ifindex': '1.3.6.1.4.1.9.9.23.1.2.1.1.6',   # cdpCacheIfIndex
        'remote_device': '1.3.6.1.4.1.9.9.23.1.2.1.1.6',   # cdpCacheDeviceId
        'remote_port': '1.3.6.1.4.1.9.9.23.1.2.1.1.7',     # cdpCacheDevicePort
        'remote_platform': '1.3.6.1.4.1.9.9.23.1.2.1.1.8', # cdpCachePlatform
        'address_type': '1.3.6.1.4.1.9.9.23.1.2.1.1.4',    # cdpCacheAddressType
        'remote_ip': '1.3.6.1.4.1.9.9.23.1.2.1.1.5',       # cdpCacheAddress
    }

    # 修正：cdpCacheDeviceId 的 OID 实际上是 1.3.6.1.4.1.9.9.23.1.2.1.1.6
    # 但上面的 local_ifindex 也用了同一个？不对，需要查标准。
    # 实际上标准 MIB：
    # cdpCacheIfIndex      1.3.6.1.4.1.9.9.23.1.2.1.1.2
    # cdpCacheDeviceId     1.3.6.1.4.1.9.9.23.1.2.1.1.6
    # 所以修正如下：
    oid_map_correct = {
        'local_ifindex': '1.3.6.1.4.1.9.9.23.1.2.1.1.2',
        'remote_device': '1.3.6.1.4.1.9.9.23.1.2.1.1.6',
        'remote_port': '1.3.6.1.4.1.9.9.23.1.2.1.1.7',
        'remote_platform': '1.3.6.1.4.1.9.9.23.1.2.1.1.8',
        'address_type': '1.3.6.1.4.1.9.9.23.1.2.1.1.4',
        'remote_ip': '1.3.6.1.4.1.9.9.23.1.2.1.1.5',
    }
    oid_map = oid_map_correct


    # 收集原始数据
    raw_data = {}  # key: (ifindex, remote_index) 或类似，CDP 表通常以 ifIndex 和邻居索引为键
    # CDP 表的索引通常是 ifIndex 和邻居索引（从1开始），但 snmpwalk 返回的 OID 格式为 .1.3.6.1.4.1.9.9.23.1.2.1.1.x.ifIndex.neighborIndex
    # 我们需要解析 OID 提取 ifIndex 和 neighborIndex

    for key, oid in oid_map.items():
        entries = snmp_walk(ip, oid, community, timeout=10, retries=3)
        for oid_str, val in entries:
            # 解析 OID 格式：... .1.3.6.1.4.1.9.9.23.1.2.1.1.<field>.<ifIndex>.<neighborIndex>
            parts = oid_str.split('.')
            # 找到最后两个数字作为 ifIndex 和 neighborIndex
            if len(parts) < 2:
                continue
            try:
                if_index = parts[-2]
                neighbor_idx = parts[-1]
            except IndexError:
                continue
            composite_key = (if_index, neighbor_idx)
            if composite_key not in raw_data:
                raw_data[composite_key] = {}
            val_str = decode_snmp_string(val)
            # 过滤无效值
            if "No Such Instance" in val_str or not val_str.strip():
                continue
            raw_data[composite_key][key] = val_str

    neighbors = []
    for (if_index, neighbor_idx), data in raw_data.items():
        # 本地接口名称需要通过 ifIndex 映射，这里只返回 ifIndex，由调用方通过 interface_map 转换
        # 或者尝试从设备获取 ifDescr（但可能需要额外 SNMP 请求，这里不做了）
        local_interface = f"Port-{if_index}"  # 占位符，实际应使用 interface_map
        remote_device = data.get('remote_device', '')
        remote_port = data.get('remote_port', '')
        remote_platform = data.get('remote_platform', '')
        remote_ip = data.get('remote_ip', '')

        # 如果 remote_ip 看起来像十六进制或不是点分十进制，尝试转换
        if remote_ip and not re.match(r'\d+\.\d+\.\d+\.\d+', remote_ip):
            # 可能是十六进制表示，如 "0A 00 00 01" 或 "0A000001"
            remote_ip = remote_ip.replace(' ', '')
            if len(remote_ip) == 8 and all(c in '0123456789ABCDEFabcdef' for c in remote_ip):
                remote_ip = '.'.join(str(int(remote_ip[i:i+2], 16)) for i in range(0,8,2))

        neighbor = {
            'local_ifindex': if_index,
            'local_interface': local_interface,  # 需要后续映射
            'remote_device': remote_device,
            'remote_port': remote_port,
            'remote_ip': remote_ip if is_valid_target_ip(remote_ip) else None,
            'remote_platform': remote_platform,
            'remote_idx': neighbor_idx,  # 保留索引供解析 IP 用
        }
        neighbors.append(neighbor)

    return neighbors



def resolve_neighbor_ip_enhanced(neighbor, addr_map, device_index=None):
    import re
    import socket

    remote_idx = neighbor.get('remote_idx', '')
    # addr_map 的 key 是 (time_mark, remote_index) 元组，需要遍历匹配
    if remote_idx and addr_map:
        for (tm, rid), ip in addr_map.items():
            if rid == remote_idx and is_valid_target_ip(ip):
                return ip

    sysname = neighbor.get('remote_sysname', '').strip()
    sysdesc = neighbor.get('remote_sysdesc', '').strip()

    if sysname:
        sysname = detect_encoding_and_fix(sysname)
    if sysdesc:
        sysdesc = detect_encoding_and_fix(sysdesc)

    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'

    # 1. 从 sysname 提取 IP
    ip_match = re.search(ip_pattern, sysname)
    if ip_match:
        ip = ip_match.group()
        if is_valid_target_ip(ip):
            return ip

    # 2. 从 sysdesc 提取 IP
    ip_match = re.search(ip_pattern, sysdesc)
    if ip_match:
        ip = ip_match.group()
        if is_valid_target_ip(ip):
            return ip

    # 3. DNS 解析
    if sysname:
        try:
            ip = socket.gethostbyname(sysname)
            if is_valid_target_ip(ip):
                return ip
        except Exception:
            pass

    # 4. 按设备名称查询 IP（优先走内存 DeviceIndex，避免逐条查库）
    if sysname:
        device = None
        if device_index is not None:
            device = device_index.by_name_exact(sysname)
            if not device:
                device = device_index.by_name_fuzzy(sysname)
        else:
            from models.models import Device

            device = Device.query.filter(func.lower(Device.name) == sysname.lower()).first()
            if not device:
                def clean_name(name):
                    if not name:
                        return ''
                    return ''.join(c for c in name if c.isalnum() or c.isspace()
                                  or c in '-_.' or '\u4e00' <= c <= '\u9fff').strip()

                clean_sysname = clean_name(sysname)
                if clean_sysname and len(clean_sysname) >= 2:
                    device = Device.query.filter(Device.name.ilike(f'%{clean_sysname}%')).first()

        if device:
            ip = device.management_ip or device.ip_address
            if ip and is_valid_target_ip(ip):
                print(f"[LLDP] 通过名称匹配到设备: {device.name} -> {ip}")
                return ip

    # 5. 兜底：从 addr_map 中取任意 IP
    for ip in addr_map.values():
        if ip and is_valid_target_ip(ip):
            return ip

    return None






from utils.snmp_oids import IF_MIB_DESCR  # ✅ 导入正确的 OID
from utils.utils import snmp_walk
import logging

logger = logging.getLogger(__name__)

def discover_interfaces_via_snmp(ip, community='public'):
    interfaces = []

    # ✅ 明确使用 ifDescr
    oid_if_descr = IF_MIB_DESCR

    logger.debug(f"[DEBUG] 开始 SNMP ifDescr walk: {ip}")

    entries = snmp_walk(
        ip=ip,
        oid=oid_if_descr,
        community=community
    )

    if not entries:
        logger.debug(f"[DEBUG] 从 {ip} 未获取到接口信息，SNMP可能失败")
        return interfaces

    # 同时采集 ifOperStatus / ifAdminStatus（按 ifIndex 建索引），不再把状态写死为 up
    def _status_map(oid):
        m = {}
        try:
            for soid, val in snmp_walk(ip=ip, oid=oid, community=community):
                idx = soid.split('.')[-1]
                m[idx] = parse_if_status(val)
        except Exception:
            pass
        return m

    oper_map = _status_map('.1.3.6.1.2.1.2.2.1.8')
    admin_map = _status_map('.1.3.6.1.2.1.2.2.1.7')

    logger.debug(f"[DEBUG] discover_interfaces_via_snmp for {ip} 获取到 {len(entries)} 个接口")

    for oid, name in entries:
        # 安全解码
        if isinstance(name, bytes):
            name = name.decode('utf-8', errors='replace')
        else:
            name = str(name).strip()

        # 提取 ifIndex
        parts = oid.split('.')
        if not parts or not parts[-1].isdigit():
            continue

        idx = parts[-1]
        logger.debug(f"[DEBUG] 接口索引 {idx}: '{name}'")

        # 过滤逻辑接口（保持你原来的逻辑）
        name_lower = name.lower()
        if any(k in name_lower for k in ['null', 'loopback', 'inloop', 'cpu', 'register-tunnel']):
            logger.debug(f"[DEBUG] 跳过逻辑接口: {name}")
            continue

        interfaces.append({
            'index': idx,
            'name': name,
            'speed': 1000,
            'mtu': 1500,
            'mac_address': '',
            'oper_status': oper_map.get(idx, 'unknown'),
            'admin_status': admin_map.get(idx, 'unknown'),
        })

    logger.debug(f"[DEBUG] 设备 {ip} 最终保留 {len(interfaces)} 个物理接口")
    return interfaces
# ====================== 后台发现任务 ======================

def background_discovery(task_id, app):
    with app.app_context():
        try:
            from models.models import db, DiscoveryTask, DiscoveryResult, Device, Interface, ConnectionPath
            from services.device_service import merge_devices_by_ip_mac
        except ImportError as e:
            print(f"[ERROR] 导入模型失败: {e}")
            return

        print(f"[DEBUG] 后台任务 {task_id} 已启动")
        task = DiscoveryTask.query.get(task_id)
        if not task:
            print(f"[DEBUG] 任务 {task_id} 不存在")
            return

        stop_event = stop_events.get(task_id) or threading.Event()
        stop_events[task_id] = stop_event

        task.status = 'running'
        task.last_run = datetime.utcnow()
        task.progress = 0
        task.discovered_count = 0
        task.connection_count = 0
        db.session.commit()

        try:
            if task.discovery_mode == 'ipmac':
                print("[DEBUG] 开始执行 IP/MAC 发现")
                run_ipmac_discovery(task, stop_event)
            else:
                print("[DEBUG] 开始执行协议发现")
                # ===== 传递 app =====
                run_protocol_discovery(task, stop_event, app)
            
            if not stop_event.is_set():
                print("[DEBUG] 发现完成，开始合并重复设备...")
                merge_result = merge_devices_by_ip_mac()
                print(f"[DEBUG] 合并完成，共合并 {merge_result.get('merged_count', 0)} 个设备")
            
        except Exception as e:
            import traceback
            print(f"[ERROR] 后台任务 {task_id} 异常: {traceback.format_exc()}")
            task.status = 'failed'
            task.last_error = str(e)
            db.session.commit()
        else:
            if stop_event.is_set():
                task.status = 'paused'
            else:
                task.status = 'completed'
                task.progress = 100
            db.session.commit()
        finally:
            if task_id in stop_events:
                del stop_events[task_id]
            print(f"[DEBUG] 任务 {task_id} 结束，状态设为 {task.status}")


import ipaddress

import logging
from utils.utils import snmp_walk

logger = logging.getLogger(__name__)


from collections import defaultdict

def discover_neighbors_via_snmp_mac(ip, community, interface_map, default_community='public', device_index=None):
    """
    通过 SNMP MAC 表发现邻居设备
    适用于不支持 LLDP/CDP 但支持 SNMP 的设备
    """
    from models.models import Device
    from utils.utils import snmp_walk, snmp_get
    import re

    neighbors = []
    
    # 获取 MAC 表（尝试多个OID）
    fdb_entries = []
    oids = [
        '1.3.6.1.2.1.17.4.3.1.2',   # dot1dTpFdbPort (BRIDGE-MIB)
        '1.3.6.1.2.1.17.7.1.2.2.1.2' # Q-BRIDGE-MIB
    ]
    
    for oid in oids:
        entries = snmp_walk(ip, oid, community, timeout=5)
        if entries:
            fdb_entries = entries
            print(f"[SNMP MAC] 使用 OID {oid} 获取到 {len(entries)} 条MAC条目")
            break
    
    if not fdb_entries:
        print(f"[SNMP MAC] 从 {ip} 未获取到MAC表")
        return neighbors

    mac_to_port = {}
    for oid, port_val in fdb_entries:
        parts = oid.split('.')
        if len(parts) < 6:
            continue
        mac_hex = parts[-6:]
        mac_str = ':'.join(f'{int(x):02x}' for x in mac_hex)
        mac_to_port[mac_str] = str(port_val).strip()

    # 获取 ARP 表
    arp_entries = snmp_walk(ip, '1.3.6.1.2.1.4.22.1.2', community, timeout=5)
    ip_to_mac = {}
    for oid, mac_val in arp_entries:
        parts = oid.split('.')
        if len(parts) < 4:
            continue
        ip_parts = parts[-4:]
        ip_str = '.'.join(ip_parts)
        if not is_valid_target_ip(ip_str):
            continue
        if isinstance(mac_val, bytes) and len(mac_val) == 6:
            mac_clean = ':'.join(f'{b:02x}' for b in mac_val)
        else:
            mac_clean = str(mac_val).replace(':', '').lower()
            if len(mac_clean) == 12:
                mac_clean = ':'.join(mac_clean[i:i+2] for i in range(0, 12, 2))
        ip_to_mac[ip_str] = mac_clean

    # 按端口分组 MAC，区分真级联口与虚拟化宿主机上行口
    port_macs = defaultdict(list)
    for mac, port_idx in mac_to_port.items():
        port_macs[port_idx].append(mac)
    port_class_info = {}
    for port_idx, macs in port_macs.items():
        port_class_info[port_idx] = classify_port_macs(macs)

    # 匹配 MAC 和 IP
    processed_macs = set()
    for mac, port_idx in mac_to_port.items():
        # 跳过已经处理过的MAC
        if mac in processed_macs:
            continue

        info = port_class_info.get(port_idx) or {}
        cls = info.get('class', 'leaf')
        if cls == 'switch_cascade':
            print(f"[SNMP MAC] 端口 {port_idx} 上有 {len(port_macs.get(port_idx, []))} 个非虚拟化 MAC，视为级联/上行口，跳过")
            continue
        if cls == 'hypervisor':
            # 宿主机上行口：只保留物理网卡 MAC，虚拟网卡 MAC 不参与建链
            physical_set = {vm_normalize_mac(m) for m in info.get('physical_macs', [])}
            if not physical_set:
                print(f"[SNMP MAC] 端口 {port_idx} 上全部为虚拟机 MAC，无法确定宿主机物理网卡，跳过")
                continue
            if vm_normalize_mac(mac) not in physical_set:
                continue
            print(f"[SNMP MAC] 端口 {port_idx} 判定为虚拟化宿主机上行口"
                  f"（{info.get('vm_count', 0)} 个 VM MAC，平台={info.get('platform') or 'unknown'}），"
                  f"仅处理物理网卡 MAC {mac}")

        local_if_name = interface_map.get(port_idx, f"Port-{port_idx}")
        
        # 查找该 MAC 对应的 IP
        matched_ip = None
        for ip_addr, mac_arp in ip_to_mac.items():
            if mac_arp == mac and ip_addr != ip:
                matched_ip = ip_addr
                break
        
        # 如果有 IP，尝试获取对端接口名
        remote_iface = 'unknown'
        if matched_ip:
            remote_device = device_index.by_ip_get(matched_ip) if device_index else Device.query.filter(
                (Device.management_ip == matched_ip) | (Device.ip_address == matched_ip)
            ).first()
            remote_community = remote_device.snmp_community if remote_device else default_community
            
            # 尝试获取对端接口
            try:
                remote_iface = get_remote_interface_by_mac(matched_ip, mac, remote_community, timeout=5)
                if not remote_iface:
                    remote_iface = 'unknown'
            except Exception as e:
                print(f"[SNMP MAC] 获取对端接口失败: {e}")
                remote_iface = 'unknown'
        
        # ===== 检查是否有 IP 或 MAC =====
        has_ip = matched_ip and is_valid_target_ip(matched_ip)
        has_mac = mac and len(mac.replace(':', '').replace('-', '')) == 12
        
        if has_ip or has_mac:
            neighbor = {
                'local_interface': local_if_name,
                'ip': matched_ip,
                'remote_interface': remote_iface,
                'remote_mac': mac,  # 保存 MAC
                'neighbor_type': 'hypervisor' if cls == 'hypervisor' else 'device',
                'vm_mac_count': info.get('vm_count', 0) if cls == 'hypervisor' else 0,
                'hypervisor_platform': info.get('platform', '') if cls == 'hypervisor' else '',
            }
            neighbors.append(neighbor)
            processed_macs.add(mac)
            print(f"[SNMP MAC] 发现邻居: IP={matched_ip}, MAC={mac}, 本地端口={local_if_name}")
        else:
            print(f"[SNMP MAC] 跳过MAC {mac}：无有效IP且MAC格式无效")

    return neighbors

@topology_bp.route('/physical_topology')
@login_required
@permission_required('topology:view')
def physical_topology():
    """物理拓扑图"""
    from models.models import Device,ConnectionPath,TopologySetting
    devices = Device.query.all()
    connections = ConnectionPath.query.all()
    devices_by_location = {}
    for device in devices:
        location_name = device.location.name if device.location else "未分配位置"
        devices_by_location.setdefault(location_name, []).append(device)

    layout_setting = TopologySetting.query.filter_by(setting_key='physical_layout_type', category='visualization').first()
    layout_type = 'hierarchical'
    if layout_setting:
        layout_type = layout_setting.get_value()

    return render_template('topology/physical.html',
                           devices=devices,
                           connections=connections,
                           devices_by_location=devices_by_location,
                           layout_type=layout_type)


@topology_bp.route('/graph', endpoint='graph')
@login_required
@permission_required('topology:view')
def topology_graph_view():
    """G6 拓扑视图（AntV G6 渲染，对标 DCOS 拓扑）"""
    from models.models import Device, ConnectionPath
    device_count = Device.query.filter(Device.is_decommissioned.is_(False)).count()
    link_count = ConnectionPath.query.count()
    return render_template('topology/topology_view.html',
                           device_count=device_count,
                           link_count=link_count)


@topology_bp.route('/server_link_verify')
@login_required
@permission_required('topology:view')
def server_link_verify():
    """服务器（宿主机）与交换机端口连接核对表。

    把「交换机端口 ↔ 宿主机物理网卡 MAC ↔ BMC MAC ↔ 管理 IP」整理成一张对应表，
    并标出每条链路的发现协议与状态，支持 CSV 导出。
    """
    import csv
    import io as _io
    from flask import Response
    from utils.vm_oui import format_mac as fmt_mac, is_vm_mac

    export_csv = request.args.get('export') == 'csv'

    PLATFORM_LABELS = {
        'vmware': 'VMware',
        'hyperv': 'Hyper-V',
        'kvm': 'KVM/QEMU',
        'proxmox': 'Proxmox',
        'xen': 'Xen/Citrix',
        'virtualbox': 'VirtualBox',
        'parallels': 'Parallels',
        'other': '其他',
    }

    servers = Device.query.filter(
        or_(
            Device.device_type.in_(['server', 'virtualization_host', 'virtual']),
            Device.is_virtual_host == True,
        )
    ).order_by(Device.name).all()

    rows = []
    for server in servers:
        # 服务器侧物理网卡 MAC（排除虚拟网卡 OUI）
        iface_macs = []
        for iface in Interface.query.filter_by(device_id=server.id).all():
            if iface.mac_address and not is_vm_mac(iface.mac_address)[0]:
                mac_disp = fmt_mac(iface.mac_address)
                if mac_disp:
                    iface_macs.append(mac_disp)
        iface_macs = list(dict.fromkeys(iface_macs))
        if not iface_macs and server.mac_address:
            iface_macs = [fmt_mac(server.mac_address)]

        platform_label = PLATFORM_LABELS.get(server.virtualization_type or '', '') or \
            ('虚拟化宿主机' if server.is_virtual_host else '')

        conns = ConnectionPath.query.filter(
            or_(
                ConnectionPath.source_device_id == server.id,
                ConnectionPath.target_device_id == server.id,
            )
        ).order_by(ConnectionPath.updated_at.desc()).all()

        if not conns:
            rows.append({
                'server': server.name,
                'mgmt_ip': server.management_ip or server.ip_address or '',
                'bmc_ip': server.bmc_ip or '',
                'bmc_mac': fmt_mac(server.bmc_mac),
                'virtualization': platform_label,
                'is_virtual_host': server.is_virtual_host or False,
                'host_macs': '; '.join(iface_macs),
                'switch': '',
                'switch_port': '',
                'protocol': '',
                'link_status': '未发现连接',
            })
            continue

        for cp in conns:
            is_src = cp.source_device_id == server.id
            other_dev = Device.query.get(cp.target_device_id if is_src else cp.source_device_id)
            rows.append({
                'server': server.name,
                'mgmt_ip': server.management_ip or server.ip_address or '',
                'bmc_ip': server.bmc_ip or '',
                'bmc_mac': fmt_mac(server.bmc_mac),
                'virtualization': platform_label,
                'is_virtual_host': server.is_virtual_host or False,
                'host_macs': '; '.join(iface_macs),
                'switch': other_dev.name if other_dev else '未知',
                'switch_port': (cp.target_port if is_src else cp.source_port) or 'unknown',
                'protocol': cp.discovery_protocol or cp.discovered_by or '',
                'link_status': cp.link_status or 'unknown',
            })

    if export_csv:
        buf = _io.StringIO()
        buf.write('\ufeff')  # Excel 识别 UTF-8
        writer = csv.writer(buf)
        writer.writerow(['服务器名称', '管理IP', 'BMC IP', 'BMC MAC', '虚拟化类型', '宿主机',
                         '物理网卡MAC', '对端交换机', '交换机端口', '发现协议', '链路状态'])
        for r in rows:
            writer.writerow([
                r['server'], r['mgmt_ip'], r['bmc_ip'], r['bmc_mac'],
                r['virtualization'], '是' if r['is_virtual_host'] else '否',
                r['host_macs'], r['switch'], r['switch_port'], r['protocol'], r['link_status'],
            ])
        return Response(
            buf.getvalue(),
            mimetype='text/csv; charset=utf-8',
            headers={'Content-Disposition': 'attachment; filename=server_link_verify.csv'},
        )

    stats = {
        'total': len(servers),
        'virtual_hosts': sum(1 for s in servers if s.is_virtual_host),
        'with_link': len({r['server'] for r in rows if r['switch']}),
        'no_link': len(servers) - len({r['server'] for r in rows if r['switch']}),
    }
    return render_template('topology/server_link_verify.html', rows=rows, stats=stats)


@topology_bp.route('/logical_topology')
@login_required
@permission_required('topology:view')
def logical_topology():
    """逻辑拓扑图"""
    topologies = LogicalTopology.query.filter_by(enabled=True).order_by(LogicalTopology.name).all()
    topology_id = request.args.get('topology_id', type=int)
    topology = None
    if topology_id:
        topology = LogicalTopology.query.get(topology_id)
    if not topology and topologies:
        topology = topologies[0]
    group_options = [
        {'value': 'vlan', 'label': '按VLAN分组'},
        {'value': 'subnet', 'label': '按子网分组'},
        {'value': 'location', 'label': '按位置分组'},
        {'value': 'device_type', 'label': '按设备类型分组'},
        {'value': 'department', 'label': '按部门分组'},
    ]
    return render_template('topology/logical.html',
                           topologies=topologies,
                           topology=topology,
                           group_options=group_options)

@topology_bp.route('/auto_discovery')
@login_required
@permission_required('topology:view')
def auto_discovery():
    """自动拓扑发现页面（旧路由，指向新模板；兼容保留，补上 controllers 查询）"""
    controllers = Device.query.filter_by(is_wireless_controller=True).order_by(Device.name).all()
    ac_job = request.args.get('ac_job')
    return render_template('topology/discovery.html', controllers=controllers, ac_job=ac_job)

@topology_bp.route('/discovery')
@login_required
@permission_required('topology:view')
def discovery():
    """拓扑发现页面（新路由）"""
    controllers = Device.query.filter_by(is_wireless_controller=True).order_by(Device.name).all()
    ac_job = request.args.get('ac_job')
    return render_template('topology/discovery.html', controllers=controllers, ac_job=ac_job)


@topology_bp.route('/discover_aps', methods=['POST'])
@login_required
@permission_required('topology:discover')
def discover_aps():
    """按无线控制器设备触发 AP 发现（CAPWAP / AC 发现）。

    改为异步：立即启动后台线程并返回 job_id，前端轮询进度，避免 SNMP 遍历
    大量交换机时 HTTP 请求超过 nginx 超时被 504 掐断。
    """
    from utils.ac_discovery import start_ac_discovery
    controller_id = request.form.get('controller_id', type=int)
    controller = Device.query.get(controller_id) if controller_id else None
    if not controller or not controller.is_wireless_controller:
        flash('请选择有效的无线控制器设备', 'warning')
        return redirect(url_for('topology.discovery'))
    # 允许在前端覆盖 community / 版本（AC 的 SNMP 凭证常与普通设备不同）
    community = request.form.get('ac_community', '').strip() or None
    version = request.form.get('ac_version', '').strip() or None
    custom_base = request.form.get('ac_custom_oid', '').strip() or None
    try:
        job_id = start_ac_discovery(controller_id, community=community,
                                    version=version, custom_base=custom_base)
    except Exception as e:
        logger.exception(f"启动 AC 发现失败: {e}")
        flash(f"启动 AP 发现失败: {e}", 'danger')
        return redirect(url_for('topology.discovery'))
    return redirect(url_for('topology.discovery', ac_job=job_id))


@topology_bp.route('/discover_aps_status/<job_id>')
@login_required
@permission_required('topology:view')
def discover_aps_status(job_id):
    """返回异步 AP 发现任务的实时进度与日志（供前端轮询）。"""
    from utils.ac_discovery import get_ac_job
    job = get_ac_job(job_id)
    if not job:
        return jsonify({'error': '任务不存在或已过期', 'done': True}), 404
    return jsonify({
        'phase': job.get('phase', ''),
        'current': job.get('current', 0),
        'total': job.get('total', 0),
        'percent': job.get('percent', 0),
        'log': job.get('log', []),
        'done': job.get('done', False),
        'failed': job.get('failed', False),
        'result': job.get('result'),
        'error': job.get('error'),
    })


@topology_bp.route('/probe_ac_mib', methods=['POST'])
@login_required
@permission_required('topology:discover')
def probe_ac_mib():
    """MIB 诊断：walk 一组候选 OID，返回每个 OID 的命中行数与样本，帮助定位真实 AP 表 OID。"""
    from utils.ac_discovery import probe_ac_mib as do_probe
    controller_id = request.form.get('controller_id', type=int)
    controller = Device.query.get(controller_id) if controller_id else None
    if not controller or not controller.is_wireless_controller:
        return jsonify({'error': '请选择有效的无线控制器设备'}), 400
    community = request.form.get('ac_community', '').strip() or None
    version = request.form.get('ac_version', '').strip() or None
    try:
        data = do_probe(controller, community=community, version=version)
    except Exception as e:
        logger.exception(f"MIB 诊断失败: {e}")
        return jsonify({'error': str(e)}), 500
    return jsonify(data)

@topology_bp.route('/connection_relations')
@login_required
@permission_required('topology:view')
def connection_relations():
    """连接关系管理"""
    device_id = request.args.get('device_id', type=int)
    connection_type = request.args.get('type', 'all')
    status = request.args.get('status', 'all')

    query = ConnectionPath.query
    if device_id:
        query = query.filter(
            or_(
                ConnectionPath.source_device_id == device_id,
                ConnectionPath.target_device_id == device_id
            )
        )
    if connection_type != 'all':
        query = query.filter(ConnectionPath.connection_type == connection_type)
    if status != 'all':
        query = query.filter(ConnectionPath.link_status == status)

    sort_by = request.args.get('sort_by', 'created_at')
    order = request.args.get('order', 'desc')
    if sort_by == 'created_at':
        query = query.order_by(
            ConnectionPath.created_at.desc() if order == 'desc' else ConnectionPath.created_at.asc()
        )
    elif sort_by == 'source_device':
        query = query.order_by(
            ConnectionPath.source_device_id.desc() if order == 'desc' else ConnectionPath.source_device_id.asc()
        )
    elif sort_by == 'target_device':
        query = query.order_by(
            ConnectionPath.target_device_id.desc() if order == 'desc' else ConnectionPath.target_device_id.asc()
        )
    connections = query.all()

    devices = Device.query.order_by(Device.name).all()
    stats = {
        'total': ConnectionPath.query.count(),
        'active': ConnectionPath.query.filter_by(link_status='active').count(),
        'down': ConnectionPath.query.filter_by(link_status='down').count(),
        'degraded': ConnectionPath.query.filter_by(link_status='degraded').count(),
        'physical': ConnectionPath.query.filter_by(connection_type='physical').count(),
        'virtual': ConnectionPath.query.filter_by(connection_type='virtual').count(),
        'trunk': ConnectionPath.query.filter_by(connection_type='trunk').count(),
    }

    # 构建图谱数据(节点=设备, 边=连接), 供 ECharts 力导向图使用
    import json
    node_map = {}
    for c in connections:
        for dev, did in [(c.source_device, c.source_device_id), (c.target_device, c.target_device_id)]:
            if did and did not in node_map:
                node_map[did] = {
                    'id': did,
                    'name': dev.name if dev else ('设备#' + str(did)),
                    'device_type': (dev.device_type if dev else 'unknown') or 'unknown',
                    'ip_address': dev.ip_address if dev else '',
                }
    graph_nodes = list(node_map.values())
    graph_edges = []
    for c in connections:
        graph_edges.append({
            'source': c.source_device_id,
            'target': c.target_device_id,
            'status': c.link_status or 'unknown',
            'type': c.connection_type or 'physical',
            'bandwidth': c.bandwidth or 0,
            'source_port': c.source_port or '',
            'target_port': c.target_port or '',
            'media_type': c.media_type or '',
        })

    return render_template('topology/connections.html',
                           connections=connections,
                           devices=devices,
                           stats=stats,
                           device_id=device_id,
                           connection_type=connection_type,
                           status=status,
                           sort_by=sort_by,
                           order=order,
                           graph_data=json.dumps({'nodes': graph_nodes, 'edges': graph_edges}, ensure_ascii=False))

@topology_bp.route('/topology_settings')
@login_required
@permission_required('topology:view')
def topology_settings():
    """拓扑设置"""
    categories = db.session.query(TopologySetting.category).distinct().all()
    settings_by_category = {}
    for category in categories:
        category_name = category[0]
        settings = TopologySetting.query.filter_by(category=category_name).order_by(TopologySetting.setting_key).all()
        if settings:
            settings_by_category[category_name] = settings
    default_layouts = TopologyLayout.query.filter_by(is_default=True, enabled=True).all()
    return render_template('topology/settings.html',
                           settings_by_category=settings_by_category,
                           default_layouts=default_layouts)

@topology_bp.route('/interface/view')
@login_required
@permission_required('topology:view')
def interface_view():
    """接口视图"""
    try:
        all_devices = Device.query.all()
        active_devices = Device.query.all()
        interface_data = []
        for device in active_devices:
            interfaces = Interface.query.filter_by(device_id=device.id).all()
            for interface in interfaces:
                interface_data.append({
                    'id': interface.id,
                    'device_id': device.id,
                    'device_name': device.name,
                    'device_ip': device.ip_address or device.management_ip or 'N/A',
                    'interface_name': interface.name,
                    'interface_type': interface.type or 'Ethernet',
                    'status': interface.admin_status or interface.oper_status or 'unknown',
                    'speed': interface.speed,
                    'mtu': interface.mtu,
                    'description': interface.description or '',
                    'mac_address': interface.mac_address or '',
                    'ip_address': interface.ip_address or '',
                    'subnet_mask': interface.subnet_mask or '',
                    'vlan': interface.vlan,
                    'in_utilization': interface.in_utilization or 0,
                    'out_utilization': interface.out_utilization or 0,
                    'last_seen': interface.updated_at.strftime('%Y-%m-%d %H:%M:%S') if interface.updated_at else 'N/A'
                })
        return render_template('topology/interface_view.html', interfaces=interface_data, devices=all_devices)
    except Exception as e:
        print(f"ERROR: 接口视图出错: {str(e)}")
        traceback.print_exc()
        return render_template('topology/interface_view.html', interfaces=[], devices=[])

@topology_bp.route('/interface/debug')
@login_required
@permission_required('topology:view')
def interface_debug():
    """接口调试页面"""
    devices = Device.query.all()
    return render_template('topology/interface_debug.html', devices=devices)

@topology_bp.route('/interface/snmp_test')
@login_required
@permission_required('topology:view')
def snmp_test_page():
    """SNMP测试页面"""
    devices = Device.query.all()
    return render_template('topology/snmp_test.html', devices=devices)

# ====================== API 路由 ======================
@topology_bp.route('/api/list')
@login_required
@permission_required('topology:view')
def api_device_list():
    """返回所有设备的基本信息，用于下拉选择"""
    devices = Device.query.all()
    device_list = [{
        'id': d.id,
        'name': d.name,
        'ip_address': d.management_ip or d.ip_address
    } for d in devices]
    return jsonify(device_list)

@topology_bp.route('/api/physical_data')
@login_required
@permission_required('topology:view')
def api_physical_data():
    """获取物理拓扑数据"""
    from models.models import Device,ConnectionPath
    devices = Device.query.all()
    #connections = ConnectionPath.query.filter_by(link_status='active').all()
    connections = ConnectionPath.query.all()   # 获取所有连接，包括 down 和 degraded

    nodes = []
    for device in devices:
        color_map = {
            'online': '#28a745',
            'offline': '#dc3545',
            'warning': '#ffc107',
            'unknown': '#6c757d'
        }
        color = color_map.get(device.status, '#6c757d')
        shape_map = {
            'server': 'square',
            'switch': 'triangle',
            'router': 'diamond',
            'firewall': 'hexagon',
            'storage': 'ellipse',
            'vm': 'circle',
            'printer': 'star',
            'ap': 'pin',
        }
        shape = shape_map.get(device.device_type, 'circle')
        icon_map = {
            'server': 'fa-server',
            'switch': 'fa-network-wired',
            'router': 'fa-route',
            'firewall': 'fa-shield-alt',
            'storage': 'fa-hdd',
            'vm': 'fa-cloud',
            'printer': 'fa-print',
            'ap': 'fa-wifi',
        }
        icon = icon_map.get(device.device_type, 'fa-desktop')
        size_map = {
            'server': 40,
            'switch': 35,
            'router': 35,
            'firewall': 30,
            'storage': 30,
            'vm': 25,
            'printer': 25,
            'ap': 28,
        }
        size = size_map.get(device.device_type, 30)

        node = {
            'id': device.id,
            'label': device.name,
            'title': f"""
                <strong>{device.name}</strong><br>
                IP: {device.management_ip or device.ip_address or 'N/A'}<br>
                类型: {device.device_type}<br>
                状态: {device.status}<br>
                位置: {device.location.name if device.location else '未分配'}<br>
                机柜: {device.cabinet.name if device.cabinet else '未分配'}
            """,
            'color': color,
            'shape': shape,
            'icon': icon,
            'size': size,
            'borderWidth': 2,
            'data': {
                'type': device.device_type,
                'ip': device.management_ip or device.ip_address,
                'status': device.status,
                'location': device.location.name if device.location else None,
            }
        }
        nodes.append(node)

    edges = []
    for conn in connections:
        color_map = {
            'active': '#28a745',
            'down': '#dc3545',
            'degraded': '#ffc107',
        }
        color = color_map.get(conn.link_status, '#6c757d')
        width = 3 if conn.connection_type == 'trunk' or (conn.bandwidth and conn.bandwidth >= 1000000000) else 2 if (conn.bandwidth and conn.bandwidth >= 100000000) else 1
        dashes = conn.link_status != 'active'

        edge = {
            'id': conn.id,
            'from': conn.source_device_id,
            'to': conn.target_device_id,
            'label': f"{conn.source_port} ↔ {conn.target_port}",
            'title': f"""
                <strong>连接详情</strong><br>
                源端口: {conn.source_port}<br>
                目标端口: {conn.target_port}<br>
                类型: {conn.connection_type}<br>
                状态: {conn.link_status}<br>
                VLAN: {conn.vlan_id or 'N/A'}<br>
                带宽: {conn.bandwidth // 1000000 if conn.bandwidth else 'N/A'} Mbps
            """,
            'color': color,
            'width': width,
            'dashes': dashes,
            'smooth': {'type': 'curvedCW', 'roundness': 0.2},
            'data': {
                'source_port': conn.source_port,
                'target_port': conn.target_port,
                'type': conn.connection_type,
                'status': conn.link_status,
                'vlan': conn.vlan_id,
                'bandwidth': conn.bandwidth,
            }
        }
        edges.append(edge)

    return jsonify({'nodes': nodes, 'edges': edges, 'timestamp': datetime.utcnow().isoformat()})

@topology_bp.route('/api/topology-graph')
@login_required
@permission_required('topology:view')
def api_topology_graph():
    """返回 AntV G6 格式的实时拓扑数据（节点/边/分组）。

    数据来自 LLDP/CDP/SNMP 自动发现写入的 ConnectionPath 以及 Device 资产表，
    与 DCOS 的 link/relationship 表同构。节点按设备类型着色、按位置/机柜分组(combos)。

    scope=connected（默认）：仅展示参与连接的设备；scope=all：展示全部设备。
    当 scope=connected 且尚无任何连接时，自动回退到全部设备，避免空白图。
    """
    from models.models import Device, ConnectionPath

    scope = request.args.get('scope', 'connected').lower()
    conns = ConnectionPath.query.all()
    device_ids = set()
    for c in conns:
        if c.source_device_id:
            device_ids.add(c.source_device_id)
        if c.target_device_id:
            device_ids.add(c.target_device_id)

    fallback_all = False
    if scope == 'all' or not device_ids:
        if not device_ids:
            fallback_all = True
        all_ids = [did for (did,) in
                   db.session.query(Device.id).all()]
        device_ids = set(all_ids)

    devices = Device.query.filter(Device.id.in_(device_ids)).all() if device_ids else []
    dev_by_id = {d.id: d for d in devices}

    # 设备类型 -> G6 形状 & 颜色（参照 DCOS 设备图标配色）
    SHAPE = {
        'router': 'circle', 'switch': 'rect', 'firewall': 'triangle',
        'server': 'diamond', 'storage': 'rect', 'load_balancer': 'triangle',
        'ap': 'circle', 'pc': 'rect', 'printer': 'rect', 'host': 'rect',
        'virtual_machine': 'rect', 'unknown': 'circle',
    }
    COLOR = {
        'router': '#1890ff', 'switch': '#13c2c2', 'firewall': '#fa8c16',
        'server': '#722ed1', 'storage': '#2f54eb', 'load_balancer': '#eb2f96',
        'ap': '#f759ab', 'pc': '#52c41a', 'printer': '#a0d911',
        'host': '#13c2c2', 'virtual_machine': '#9254de', 'unknown': '#8c8c8c',
    }

    def group_of(d):
        if d.location and getattr(d.location, 'name', None):
            return d.location.name
        if d.cabinet and getattr(d.cabinet, 'name', None):
            return '机柜-%s' % d.cabinet.name
        return '未分配'

    nodes = []
    combos = {}
    for d in devices:
        t = (d.device_type or 'unknown').lower()
        color = COLOR.get(t, COLOR['unknown'])
        online = (d.status or '').lower() == 'online'
        combo_id = group_of(d)
        combos.setdefault(combo_id, {'id': combo_id, 'label': combo_id})
        nodes.append({
            'id': str(d.id),
            'label': d.name,
            'type': SHAPE.get(t, 'circle'),
            'deviceType': t,
            'ip': d.management_ip or d.ip_address or '',
            'status': d.status or 'unknown',
            'online': online,
            'vendor': d.brand or d.manufacturer or '',
            'model': d.model or '',
            'mac': d.mac_address or '',
            'comboId': combo_id,
            'color': color,
        })

    now = datetime.utcnow()

    def _link_aging(conn):
        last_seen = conn.last_seen
        if not last_seen:
            if conn.link_status == 'stale':
                return {'state': 'stale', 'label': '已老化', 'hours': None}
            return {'state': 'unknown', 'label': '未记录', 'hours': None}
        if last_seen.tzinfo is not None:
            last_seen = last_seen.replace(tzinfo=None)
        hours = max(0.0, (now - last_seen).total_seconds() / 3600.0)
        if conn.link_status == 'stale' or hours > 72:
            return {'state': 'stale', 'label': '已老化', 'hours': round(hours, 1)}
        if hours > 24:
            return {'state': 'aging', 'label': '老化中', 'hours': round(hours, 1)}
        return {'state': 'fresh', 'label': '正常', 'hours': round(hours, 1)}

    edges = []
    for c in conns:
        if c.source_device_id not in dev_by_id or c.target_device_id not in dev_by_id:
            continue
        src = str(c.source_device_id)
        tgt = str(c.target_device_id)
        status = (c.link_status or 'unknown').lower()
        aging = _link_aging(c)
        edges.append({
            'source': src,
            'target': tgt,
            'sourcePort': c.source_port or '',
            'targetPort': c.target_port or '',
            'label': '%s ↔ %s' % (c.source_port or '', c.target_port or ''),
            'protocol': c.discovery_protocol or c.discovered_by or '',
            'confidence': c.confidence if c.confidence is not None else 0,
            'bandwidth': c.bandwidth or 0,
            'media': c.media_type or '',
            'status': status,
            'connType': c.connection_type or 'physical',
            'aging_state': aging['state'],
            'aging_label': aging['label'],
            'aging_hours': aging['hours'],
            'last_seen': c.last_seen.isoformat() if c.last_seen else None,
        })

    return jsonify({
        'nodes': nodes,
        'edges': edges,
        'combos': list(combos.values()),
        'timestamp': datetime.utcnow().isoformat(),
        'scope': scope,
        'fallback_all': fallback_all,
    })


@topology_bp.route('/api/topology/ping/<int:device_id>')
@login_required
@permission_required('topology:view')
def api_topology_ping(device_id):
    """对设备管理 IP 执行 Ping 探测（按需调用，用于拓扑右键菜单）。"""
    import os
    import subprocess
    from models.models import Device

    d = Device.query.get_or_404(device_id)
    ip = d.management_ip or d.ip_address
    if not ip:
        return jsonify({'success': False, 'message': '设备无管理 IP'}), 400
    if os.name == 'nt':
        cmd = ['ping', '-n', '1', '-w', '2000', ip]
    else:
        cmd = ['ping', '-c', '1', '-W', '2', ip]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=10)
        ok = r.returncode == 0
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    return jsonify({'success': ok, 'ip': ip, 'message': '可达' if ok else '不可达'})


# ------------------------------------------------------------------ 存储光纤(SAN)拓扑（对标 DCOS「光纤拓扑」）
SAN_NODE_COLOR = {
    'switch': '#13c2c2',   # FC 交换机
    'array':  '#2f54eb',   # 存储阵列
    'server': '#722ed1',   # 服务器
    'hba':    '#fa8c16',   # HBA 卡
    'other':  '#8c8c8c',
}
SAN_NODE_SHAPE = {
    'switch': 'rect', 'array': 'circle', 'server': 'diamond',
    'hba': 'triangle', 'other': 'circle',
}


@topology_bp.route('/san')
@login_required
@permission_required('topology:view')
def san_topology_view():
    return render_template('topology/san_topology.html')


@topology_bp.route('/api/san-graph')
@login_required
@permission_required('topology:view')
def api_san_graph():
    """返回 AntV G6 格式的 SAN 拓扑（节点/边/分区 combos）。"""
    nodes = SanNode.query.all()
    node_by_id = {n.id: n for n in nodes}
    links = SanLink.query.all()

    g6_nodes, combos = [], {}
    for n in nodes:
        t = (n.node_type or 'other').lower()
        color = SAN_NODE_COLOR.get(t, SAN_NODE_COLOR['other'])
        combo_id = n.zone or '未分区'
        combos.setdefault(combo_id, {'id': combo_id, 'label': combo_id})
        g6_nodes.append({
            'id': str(n.id),
            'label': n.name,
            'type': SAN_NODE_SHAPE.get(t, 'circle'),
            'nodeType': t,
            'wwpn': n.wwpn or '',
            'vendor': n.vendor or '',
            'model': n.model or '',
            'mgmt_ip': n.mgmt_ip or '',
            'zone': n.zone or '',
            'status': n.status or 'unknown',
            'linked_device_id': n.linked_device_id,
            'comboId': combo_id,
            'color': color,
        })

    g6_edges = []
    for lnk in links:
        if lnk.source_id not in node_by_id or lnk.target_id not in node_by_id:
            continue
        st = (lnk.status or 'up').lower()
        g6_edges.append({
            'id': str(lnk.id),
            'source': str(lnk.source_id),
            'target': str(lnk.target_id),
            'sourcePort': lnk.port_source or '',
            'targetPort': lnk.port_target or '',
            'label': '%s ↔ %s' % (lnk.port_source or '', lnk.port_target or ''),
            'speed': lnk.speed or '',
            'linkType': lnk.link_type or 'fc',
            'status': st,
        })
    return jsonify({
        'nodes': g6_nodes,
        'edges': g6_edges,
        'combos': list(combos.values()),
        'timestamp': datetime.utcnow().isoformat(),
    })


@topology_bp.route('/api/san/nodes', methods=['GET'])
@login_required
@permission_required('topology:view')
def san_nodes_list():
    rows = SanNode.query.order_by(SanNode.zone, SanNode.name).all()
    return jsonify([r.to_dict() for r in rows])


@topology_bp.route('/api/san/nodes', methods=['POST'])
@login_required
@permission_required('topology:edit')
def san_nodes_create():
    d = request.get_json(force=True, silent=True) or {}
    if not d.get('name'):
        return jsonify({'error': 'name required'}), 400
    wwpn = (d.get('wwpn') or '').strip()
    if wwpn:
        dup = SanNode.query.filter_by(wwpn=wwpn).first()
        if dup:
            return jsonify({'error': 'WWPN 已存在 (节点 %s)' % dup.name}), 409
    status = d.get('status') or 'unknown'
    if status not in ('online', 'offline', 'unknown'):
        status = 'unknown'
    node = SanNode(
        name=d['name'], node_type=d.get('node_type', 'switch'),
        wwpn=wwpn, vendor=d.get('vendor'), model=d.get('model'),
        mgmt_ip=d.get('mgmt_ip'), zone=d.get('zone'),
        status=status,
        linked_device_id=d.get('linked_device_id'), note=d.get('note'))
    db.session.add(node)
    db.session.commit()
    log_audit('create', 'san_node', node.id,
              '创建 SAN 节点 %s (%s)' % (node.name, node.node_type),
              details={'name': node.name, 'node_type': node.node_type,
                       'wwpn': wwpn, 'zone': node.zone, 'status': status})
    return jsonify(node.to_dict()), 201


@topology_bp.route('/api/san/nodes/<int:nid>', methods=['GET'])
@login_required
@permission_required('topology:view')
def san_node_get(nid):
    return jsonify(SanNode.query.get_or_404(nid).to_dict())


@topology_bp.route('/api/san/nodes/<int:nid>', methods=['PUT', 'DELETE'])
@login_required
@permission_required('topology:edit')
def san_node_detail(nid):
    node = SanNode.query.get_or_404(nid)
    if request.method == 'DELETE':
        linked = SanLink.query.filter(
            (SanLink.source_id == nid) | (SanLink.target_id == nid)).count()
        SanLink.query.filter(
            (SanLink.source_id == nid) | (SanLink.target_id == nid)).delete()
        name = node.name
        db.session.delete(node)
        db.session.commit()
        log_audit('delete', 'san_node', nid,
                  '删除 SAN 节点 %s (%d 条链路已级联删除)' % (name, linked))
        return jsonify({'ok': True, 'deleted_links': linked})
    d = request.get_json(force=True, silent=True) or {}
    changes = {}
    for f in ('name', 'node_type', 'wwpn', 'vendor', 'model', 'mgmt_ip',
             'zone', 'status', 'linked_device_id', 'note'):
        if f in d and getattr(node, f) != d[f]:
            changes[f] = {'from': getattr(node, f), 'to': d[f]}
            setattr(node, f, d[f])
    db.session.commit()
    if changes:
        log_audit('update', 'san_node', nid, '更新 SAN 节点 %s' % node.name,
                  changes=changes)
    return jsonify(node.to_dict())


@topology_bp.route('/api/san/links', methods=['GET'])
@login_required
@permission_required('topology:view')
def san_links_list():
    rows = SanLink.query.order_by(SanLink.source_id, SanLink.target_id).all()
    return jsonify([r.to_dict() for r in rows])


@topology_bp.route('/api/san/links', methods=['POST'])
@login_required
@permission_required('topology:edit')
def san_links_create():
    d = request.get_json(force=True, silent=True) or {}
    try:
        source_id = int(d.get('source_id') or 0)
        target_id = int(d.get('target_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'error': 'source_id and target_id required'}), 400
    if source_id == target_id:
        return jsonify({'error': '源和目的不能相同'}), 400
    src = SanNode.query.get(source_id)
    tgt = SanNode.query.get(target_id)
    if not src or not tgt:
        return jsonify({'error': '源/目的节点不存在'}), 400
    dup = SanLink.query.filter_by(source_id=source_id, target_id=target_id).first()
    if dup:
        return jsonify({'error': '该链路已存在'}), 409
    status = d.get('status') or 'up'
    if status not in ('up', 'down', 'degraded'):
        status = 'up'
    lnk = SanLink(
        source_id=source_id, target_id=target_id,
        link_type=d.get('link_type', 'fc'), port_source=d.get('port_source'),
        port_target=d.get('port_target'), speed=d.get('speed'),
        status=status, note=d.get('note'))
    db.session.add(lnk)
    db.session.commit()
    log_audit('create', 'san_link', lnk.id,
              '创建 SAN 链路 %s -> %s (%s)' % (src.name, tgt.name, status),
              details={'source_id': source_id, 'target_id': target_id,
                       'source_name': src.name, 'target_name': tgt.name,
                       'speed': lnk.speed, 'status': status})
    return jsonify(lnk.to_dict()), 201


@topology_bp.route('/api/san/links/<int:lid>', methods=['DELETE'])
@login_required
@permission_required('topology:edit')
def san_link_detail(lid):
    lnk = SanLink.query.get_or_404(lid)
    db.session.delete(lnk)
    db.session.commit()
    log_audit('delete', 'san_link', lid, '删除 SAN 链路 #%d' % lid)
    return jsonify({'ok': True})


@topology_bp.route('/api/san/seed', methods=['POST'])
@login_required
@permission_required('topology:edit')
def san_seed():
    """写入一组示例 SAN 数据，便于体验 G6 光纤拓扑。

    改为「补全式」幂等：仅当示例中的标志性节点/链路尚不存在时才补录，
    不会因库里已有其他（可能是脏）节点而整体跳过，也不会删除已有数据。
    这样无论当前库处于何种状态，点击「载入示例」都能得到完整的双分区示例拓扑。
    """
    sample = [
        ('FC-SW-01', 'switch', '20:00:00:11:22:33:44:01', 'Brocade', 'G620', '10.1.0.11', 'Zone-A'),
        ('FC-SW-02', 'switch', '20:00:00:11:22:33:44:02', 'Cisco',  'MDS-9148S', '10.1.0.12', 'Zone-B'),
        ('SAN-ARRAY-01', 'array', '50:00:00:aa:bb:cc:dd:01', 'Dell EMC', 'Unity 480F', '10.1.0.21', 'Zone-A'),
        ('SAN-ARRAY-02', 'array', '50:00:00:aa:bb:cc:dd:02', 'NetApp',  'AFF A400', '10.1.0.22', 'Zone-B'),
        ('ESX-01', 'server', '10:00:00:ff:ee:dd:cc:01', 'Dell', 'R750', '10.1.0.31', 'Zone-A'),
        ('ESX-02', 'server', '10:00:00:ff:ee:dd:cc:02', 'HPE',  'DL380', '10.1.0.32', 'Zone-B'),
    ]
    nodes = {}
    for name, ntype, wwpn, vendor, model, ip, zone in sample:
        cur = SanNode.query.filter_by(name=name).first()
        if not cur:
            cur = SanNode(name=name, node_type=ntype, wwpn=wwpn, vendor=vendor,
                          model=model, mgmt_ip=ip, zone=zone, status='online')
            db.session.add(cur); db.session.flush()
        nodes[name] = cur.id
    links = [
        ('FC-SW-01', 'SAN-ARRAY-01', '0', '0', '32G'),
        ('FC-SW-01', 'ESX-01', '1', '1', '16G'),
        ('FC-SW-02', 'SAN-ARRAY-02', '0', '0', '32G'),
        ('FC-SW-02', 'ESX-02', '1', '1', '16G'),
        ('FC-SW-01', 'FC-SW-02', 'ISL', 'ISL', '64G'),
    ]
    added_links = 0
    for s, t, ps, pt, sp in links:
        if s in nodes and t in nodes:
            exists = SanLink.query.filter_by(source_id=nodes[s], target_id=nodes[t]).first()
            if not exists:
                db.session.add(SanLink(source_id=nodes[s], target_id=nodes[t],
                                       link_type='fc', port_source=ps, port_target=pt,
                                       speed=sp, status='up'))
                added_links += 1
    db.session.commit()
    total = SanNode.query.count()
    log_audit('execute', 'san_seed', 0,
              '载入 SAN 示例拓扑 (节点 %d, 链路 %d, 新增链路 %d)'
              % (total, len(links), added_links))
    return jsonify({'ok': True, 'nodes': total, 'links': len(links), 'added_links': added_links})


@topology_bp.route('/api/trunk_stats')
@login_required
@permission_required('topology:view')
def api_trunk_stats():
    """获取 trunk 连接的详细统计数据"""
    from models.models import Device, ConnectionPath

    trunk_conns = ConnectionPath.query.filter_by(connection_type='trunk').all()

    # 基本统计
    total = len(trunk_conns)
    active_count = sum(1 for c in trunk_conns if c.link_status == 'active')
    down_count = sum(1 for c in trunk_conns if c.link_status == 'down')
    degraded_count = sum(1 for c in trunk_conns if c.link_status == 'degraded')
    unknown_count = sum(1 for c in trunk_conns if c.link_status not in ('active', 'down', 'degraded'))

    # 涉及的设备
    device_set = set()
    for c in trunk_conns:
        device_set.add(c.source_device_id)
        device_set.add(c.target_device_id)
    devices_involved = Device.query.filter(Device.id.in_(device_set)).all() if device_set else []
    device_list = [{'id': d.id, 'name': d.name, 'type': d.device_type,
                     'ip': d.management_ip or d.ip_address,
                     'location': d.location.name if d.location else '未分配'}
                    for d in devices_involved]

    # 带宽分布
    bandwidth_dist = {}
    for c in trunk_conns:
        bw = c.bandwidth or 0
        if bw >= 10000000000:
            bw_label = '10G+'
        elif bw >= 1000000000:
            bw_label = '1G'
        elif bw >= 100000000:
            bw_label = '100M'
        elif bw > 0:
            bw_label = '<100M'
        else:
            bw_label = '未知'
        bandwidth_dist[bw_label] = bandwidth_dist.get(bw_label, 0) + 1

    # VLAN 分布
    vlan_dist = {}
    for c in trunk_conns:
        vlan = c.vlan_id or '未配置'
        vlan_dist[vlan] = vlan_dist.get(vlan, 0) + 1

    # 介质类型分布
    media_dist = {}
    for c in trunk_conns:
        media = c.media_type or '未知'
        media_dist[media] = media_dist.get(media, 0) + 1

    # 发现协议分布
    protocol_dist = {}
    for c in trunk_conns:
        proto = c.discovered_by or c.discovery_protocol or 'unknown'
        protocol_dist[proto] = protocol_dist.get(proto, 0) + 1

    # 详细连接列表
    conn_list = []
    for c in trunk_conns:
        src_dev = c.source_device
        tgt_dev = c.target_device
        conn_list.append({
            'id': c.id,
            'source_device': src_dev.name if src_dev else f'#{c.source_device_id}',
            'source_device_id': c.source_device_id,
            'source_port': c.source_port,
            'target_device': tgt_dev.name if tgt_dev else f'#{c.target_device_id}',
            'target_device_id': c.target_device_id,
            'target_port': c.target_port,
            'link_status': c.link_status or 'unknown',
            'bandwidth': c.bandwidth,
            'bandwidth_gbps': round(c.bandwidth / 1000000000, 2) if c.bandwidth else None,
            'vlan_id': c.vlan_id,
            'media_type': c.media_type or '',
            'discovered_by': c.discovered_by or '',
            'updated_at': c.updated_at.strftime('%Y-%m-%d %H:%M') if c.updated_at else '',
        })

    return jsonify({
        'total': total,
        'status_breakdown': {
            'active': active_count,
            'down': down_count,
            'degraded': degraded_count,
            'unknown': unknown_count,
        },
        'devices_involved': device_list,
        'device_count': len(device_set),
        'bandwidth_distribution': bandwidth_dist,
        'vlan_distribution': vlan_dist,
        'media_distribution': media_dist,
        'protocol_distribution': protocol_dist,
        'connections': conn_list,
    })

# ---------- 逻辑拓扑：列表 / 创建 / 设备 / 连接 ----------
@topology_bp.route('/api/topologies')
@login_required
@permission_required('topology:view')
def api_topologies():
    """逻辑拓扑列表（JSON，供 logical.html 左侧面板加载）"""
    topologies = LogicalTopology.query.order_by(LogicalTopology.name).all()
    return jsonify({'success': True,
                    'topologies': [t.to_dict() for t in topologies]})


@topology_bp.route('/api/topologies/create', methods=['POST'])
@login_required
@permission_required('topology:edit')
def create_topology():
    """新建逻辑拓扑（前端 createTopology 调用）"""
    data = request.get_json(force=True) or {}
    name = (data.get('name') or '').strip()
    topology_type = (data.get('topology_type') or 'custom').strip()
    if not name:
        return jsonify({'success': False, 'message': '拓扑名称不能为空'}), 400
    dup = LogicalTopology.query.filter_by(name=name).first()
    if dup:
        return jsonify({'success': False,
                        'message': '已存在同名逻辑拓扑「%s」' % name}), 400

    topo = LogicalTopology(
        name=name,
        description=data.get('description'),
        topology_type=topology_type,
        group_by=data.get('group_by') or None,
        group_value=data.get('group_value') or None,
        layout_type=(data.get('layout_type') or 'force').strip() or 'force',
        node_size=int(data.get('node_size') or 30),
        link_distance=int(data.get('link_distance') or 100),
        show_labels=bool(data.get('show_labels', True)),
        show_icons=bool(data.get('show_icons', True)),
        is_public=bool(data.get('is_public', True)),
        enabled=bool(data.get('enabled', True)),
        created_by=current_user.username if current_user.is_authenticated else None,
    )
    db.session.add(topo)
    db.session.commit()
    log_audit('create', 'logical_topology', topo.id,
              '创建逻辑拓扑 %s（类型 %s）' % (topo.name, topology_type),
              details={'name': topo.name, 'topology_type': topology_type,
                       'group_by': topo.group_by})
    return jsonify({'success': True, 'topology_id': topo.id,
                    'topology': topo.to_dict()}), 201


@topology_bp.route('/api/topologies/<int:tid>/devices')
@login_required
@permission_required('topology:view')
def api_topology_devices(tid):
    """某个逻辑拓扑视图下的设备列表（按当前分组方式取参与设备）"""
    group_by = request.args.get('group_by', 'device_type')
    devices, _connections = _logical_scope(group_by)
    items = []
    for d in devices:
        items.append({
            'id': d.id,
            'name': d.name,
            'ip': d.management_ip or d.ip_address or '',
            'device_type': d.device_type or 'unknown',
            'status': d.status or 'unknown',
            'location': d.location.name if d.location else '',
        })
    return jsonify({'success': True, 'devices': items, 'group_by': group_by,
                    'count': len(items)})


@topology_bp.route('/api/topologies/<int:tid>/connections')
@login_required
@permission_required('topology:view')
def api_topology_connections(tid):
    """某个逻辑拓扑视图下的连接列表（活动链路）"""
    connections = ConnectionPath.query.filter_by(link_status='active').all()
    dev_ids = set()
    for c in connections:
        dev_ids.add(c.source_device_id)
        dev_ids.add(c.target_device_id)
    dev_map = {}
    if dev_ids:
        dev_map = {d.id: d for d in
                   Device.query.filter(Device.id.in_(dev_ids)).all()}
    items = []
    for c in connections:
        s = dev_map.get(c.source_device_id)
        t = dev_map.get(c.target_device_id)
        items.append({
            'id': c.id,
            'source_device': s.name if s else str(c.source_device_id),
            'source_interface': c.source_port or '',
            'target_device': t.name if t else str(c.target_device_id),
            'target_interface': c.target_port or '',
            'type': c.connection_type or 'physical',
            'status': c.link_status or 'unknown',
        })
    return jsonify({'success': True, 'connections': items,
                    'count': len(items)})


def _logical_scope(group_by):
    """返回 (devices, connections)，语义与 generate_*_topology 保持一致。

    vlan 分组只包含参与活动链路的设备；其余分组包含全部设备。
    """
    connections = ConnectionPath.query.filter_by(link_status='active').all()
    if group_by == 'vlan':
        involved = set()
        for c in connections:
            involved.add(c.source_device_id)
            involved.add(c.target_device_id)
        devices = (Device.query.filter(Device.id.in_(involved)).all()
                   if involved else [])
    else:
        devices = Device.query.all()
    return devices, connections


@topology_bp.route('/api/logical_data')
@login_required
@permission_required('topology:view')
def api_logical_data():
    """获取逻辑拓扑数据"""
    group_by = request.args.get('group_by', 'device_type')
    topology_id = request.args.get('topology_id', type=int)

    if topology_id:
        topology = LogicalTopology.query.get(topology_id)
        if topology and topology.topology_data:
            return jsonify(topology.get_topology_data())

    devices = Device.query.all()
    connections = ConnectionPath.query.filter_by(link_status='active').all()

    # 根据分组类型生成逻辑拓扑
    if group_by == 'vlan':
        return generate_vlan_topology(devices, connections)
    elif group_by == 'subnet':
        return generate_subnet_topology(devices, connections)
    elif group_by == 'location':
        return generate_location_topology(devices, connections)
    elif group_by == 'device_type':
        return generate_device_type_topology(devices, connections)
    else:
        return generate_device_type_topology(devices, connections)

def generate_device_type_topology(devices, connections):
    dev_by_id = {d.id: d for d in devices}
    type_groups = defaultdict(list)
    for device in devices:
        type_groups[device.device_type].append(device)

    nodes = []
    group_nodes = {}
    group_id = 1000

    for group_name, group_devices in type_groups.items():
        group_node_id = group_id
        group_nodes[group_name] = group_node_id
        group_id += 1
        icon_map = {'server': 'fa-server', 'switch': 'fa-network-wired', 'router': 'fa-route',
                    'firewall': 'fa-shield-alt', 'storage': 'fa-hdd', 'vm': 'fa-cloud',
                    'printer': 'fa-print', 'ap': 'fa-wifi'}
        icon = icon_map.get(group_name, 'fa-desktop')
        nodes.append({
            'id': group_node_id,
            'label': f"{group_name} ({len(group_devices)})",
            'group': group_name,
            'shape': 'box',
            'color': '#007bff',
            'size': 40 + len(group_devices) * 2,
            'font': {'size': 16},
            'data': {'type': 'group', 'device_count': len(group_devices)}
        })

    device_nodes = {}
    for device in devices:
        color_map = {'online': '#28a745', 'offline': '#dc3545', 'warning': '#ffc107', 'unknown': '#6c757d'}
        color = color_map.get(device.status, '#6c757d')
        device_nodes[device.id] = {
            'id': device.id,
            'label': device.name,
            'group': device.device_type,
            'color': color,
            'shape': 'dot',
            'size': 20,
            'parent': group_nodes.get(device.device_type),
            'data': {'type': 'device', 'ip': device.management_ip or device.ip_address, 'status': device.status}
        }
        nodes.append(device_nodes[device.id])

    edges = []
    for conn in connections:
        source_device = dev_by_id.get(conn.source_device_id)
        target_device = dev_by_id.get(conn.target_device_id)
        if not source_device or not target_device:
            continue
        if source_device.device_type == target_device.device_type:
            edges.append({
                'id': f"conn_{conn.id}",
                'from': conn.source_device_id,
                'to': conn.target_device_id,
                'label': f"{conn.bandwidth // 1000000 if conn.bandwidth else 'N/A'}M",
                'color': '#6c757d',
                'width': 1,
                'dashes': False,
                'smooth': {'type': 'curvedCW', 'roundness': 0.1},
            })
        else:
            group_conn_id = f"group_{source_device.device_type}_{target_device.device_type}"
            existing_edge = next((e for e in edges if e['id'] == group_conn_id), None)
            if existing_edge:
                existing_edge['width'] = min(existing_edge.get('width', 2) + 0.5, 5)
                count = int(existing_edge['label'].split(' ')[0]) + 1 if ' ' in existing_edge['label'] else 2
                existing_edge['label'] = f"{count} connections"
            else:
                edges.append({
                    'id': group_conn_id,
                    'from': group_nodes.get(source_device.device_type),
                    'to': group_nodes.get(target_device.device_type),
                    'label': "1 connection",
                    'color': '#17a2b8',
                    'width': 2,
                    'dashes': False,
                    'smooth': {'type': 'curvedCW', 'roundness': 0.3},
                    'data': {'source_group': source_device.device_type, 'target_group': target_device.device_type}
                })
    return jsonify({'nodes': nodes, 'edges': edges, 'timestamp': datetime.utcnow().isoformat()})

def generate_location_topology(devices, connections):
    dev_by_id = {d.id: d for d in devices}
    location_groups = defaultdict(list)
    for device in devices:
        location_name = device.location.name if device.location else "未分配位置"
        location_groups[location_name].append(device)

    nodes = []
    group_nodes = {}
    group_id = 1000
    for location_name, location_devices in location_groups.items():
        group_node_id = group_id
        group_nodes[location_name] = group_node_id
        group_id += 1
        nodes.append({
            'id': group_node_id,
            'label': f"{location_name} ({len(location_devices)})",
            'group': 'location',
            'shape': 'box',
            'color': '#6610f2',
            'size': 40 + len(location_devices) * 2,
            'font': {'size': 16},
            'data': {'type': 'location', 'device_count': len(location_devices)}
        })

    device_nodes = {}
    for device in devices:
        location_name = device.location.name if device.location else "未分配位置"
        color_map = {'online': '#28a745', 'offline': '#dc3545', 'warning': '#ffc107', 'unknown': '#6c757d'}
        color = color_map.get(device.status, '#6c757d')
        device_nodes[device.id] = {
            'id': device.id,
            'label': device.name,
            'group': location_name,
            'color': color,
            'shape': 'dot',
            'size': 20,
            'parent': group_nodes.get(location_name),
            'data': {'type': 'device', 'ip': device.management_ip or device.ip_address, 'status': device.status, 'location': location_name}
        }
        nodes.append(device_nodes[device.id])

    location_connections = defaultdict(int)
    for conn in connections:
        source_device = dev_by_id.get(conn.source_device_id)
        target_device = dev_by_id.get(conn.target_device_id)
        if not source_device or not target_device:
            continue
        source_location = source_device.location.name if source_device.location else "未分配位置"
        target_location = target_device.location.name if target_device.location else "未分配位置"
        if source_location != target_location:
            connection_key = tuple(sorted([source_location, target_location]))
            location_connections[connection_key] += 1

    edges = []
    for (loc1, loc2), count in location_connections.items():
        edges.append({
            'id': f"loc_{loc1}_{loc2}",
            'from': group_nodes.get(loc1),
            'to': group_nodes.get(loc2),
            'label': f"{count} connections",
            'color': '#17a2b8',
            'width': min(2 + count * 0.5, 5),
            'dashes': False,
            'smooth': {'type': 'curvedCW', 'roundness': 0.3},
        })
    return jsonify({'nodes': nodes, 'edges': edges, 'timestamp': datetime.utcnow().isoformat()})

def generate_vlan_topology(devices, connections):
    vlan_groups = defaultdict(list)
    for conn in connections:
        if conn.vlan_id:
            vlans = [v.strip() for v in conn.vlan_id.split(',')]
            for vlan in vlans:
                if vlan:
                    vlan_groups[vlan].append(conn)

    nodes = []
    group_nodes = {}
    group_id = 1000
    for vlan, vlan_connections in vlan_groups.items():
        group_node_id = group_id
        group_nodes[vlan] = group_node_id
        group_id += 1
        device_ids = set()
        for conn in vlan_connections:
            device_ids.add(conn.source_device_id)
            device_ids.add(conn.target_device_id)
        nodes.append({
            'id': group_node_id,
            'label': f"VLAN {vlan} ({len(device_ids)})",
            'group': 'vlan',
            'shape': 'box',
            'color': '#20c997',
            'size': 40 + len(device_ids) * 2,
            'font': {'size': 16},
            'data': {'type': 'vlan', 'device_count': len(device_ids)}
        })

    device_vlans = defaultdict(set)
    for conn in connections:
        if conn.vlan_id:
            vlans = [v.strip() for v in conn.vlan_id.split(',')]
            for vlan in vlans:
                if vlan:
                    device_vlans[conn.source_device_id].add(vlan)
                    device_vlans[conn.target_device_id].add(vlan)

    # 仅保留参与活动链路的设备，避免 vlan 视图统计虚高（与 _logical_scope('vlan') 一致）
    involved = {c.source_device_id for c in connections}
    involved.update(c.target_device_id for c in connections)

    device_nodes = {}
    for device in devices:
        if device.id not in involved:
            continue
        color_map = {'online': '#28a745', 'offline': '#dc3545', 'warning': '#ffc107', 'unknown': '#6c757d'}
        color = color_map.get(device.status, '#6c757d')
        vlans = list(device_vlans.get(device.id, set()))
        # 只属于单个 VLAN 的设备归入对应组节点，多 VLAN 设备不归组（供前端聚类布局）
        parent = group_nodes.get(vlans[0]) if len(vlans) == 1 else None
        device_nodes[device.id] = {
            'id': device.id,
            'label': device.name,
            'color': color,
            'shape': 'dot',
            'size': 20,
            'parent': parent,
            'data': {
                'type': 'device',
                'ip': device.management_ip or device.ip_address,
                'status': device.status,
                'vlans': vlans
            }
        }
        nodes.append(device_nodes[device.id])

    edges = []
    for conn in connections:
        if conn.link_status != 'active':
            continue
        edges.append({
            'id': conn.id,
            'from': conn.source_device_id,
            'to': conn.target_device_id,
            'label': conn.vlan_id or '',
            'color': '#6c757d',
            'width': 1,
            'dashes': False,
            'smooth': {'type': 'curvedCW', 'roundness': 0.1},
        })
    return jsonify({'nodes': nodes, 'edges': edges, 'timestamp': datetime.utcnow().isoformat()})

def generate_subnet_topology(devices, connections):
    dev_by_id = {d.id: d for d in devices}
    subnet_groups = defaultdict(list)
    for device in devices:
        ip = device.management_ip or device.ip_address
        if ip:
            parts = ip.split('.')
            if len(parts) == 4:
                subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
                subnet_groups[subnet].append(device)

    nodes = []
    group_nodes = {}
    group_id = 1000
    for subnet, subnet_devices in subnet_groups.items():
        group_node_id = group_id
        group_nodes[subnet] = group_node_id
        group_id += 1
        nodes.append({
            'id': group_node_id,
            'label': f"{subnet} ({len(subnet_devices)})",
            'group': 'subnet',
            'shape': 'box',
            'color': '#fd7e14',
            'size': 40 + len(subnet_devices) * 2,
            'font': {'size': 14},
            'data': {'type': 'subnet', 'device_count': len(subnet_devices)}
        })

    device_nodes = {}
    for device in devices:
        ip = device.management_ip or device.ip_address
        subnet = None
        if ip:
            parts = ip.split('.')
            if len(parts) == 4:
                subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        color_map = {'online': '#28a745', 'offline': '#dc3545', 'warning': '#ffc107', 'unknown': '#6c757d'}
        color = color_map.get(device.status, '#6c757d')
        device_nodes[device.id] = {
            'id': device.id,
            'label': device.name,
            'group': subnet or "unknown",
            'color': color,
            'shape': 'dot',
            'size': 20,
            'parent': group_nodes.get(subnet),
            'data': {'type': 'device', 'ip': ip, 'status': device.status, 'subnet': subnet}
        }
        nodes.append(device_nodes[device.id])

    subnet_connections = defaultdict(int)
    for conn in connections:
        source_device = dev_by_id.get(conn.source_device_id)
        target_device = dev_by_id.get(conn.target_device_id)
        if not source_device or not target_device:
            continue
        source_ip = source_device.management_ip or source_device.ip_address
        target_ip = target_device.management_ip or target_device.ip_address
        if source_ip and target_ip:
            source_parts = source_ip.split('.')
            target_parts = target_ip.split('.')
            if len(source_parts) == 4 and len(target_parts) == 4:
                source_subnet = f"{source_parts[0]}.{source_parts[1]}.{source_parts[2]}.0/24"
                target_subnet = f"{target_parts[0]}.{target_parts[1]}.{target_parts[2]}.0/24"
                if source_subnet != target_subnet:
                    connection_key = tuple(sorted([source_subnet, target_subnet]))
                    subnet_connections[connection_key] += 1

    edges = []
    for (subnet1, subnet2), count in subnet_connections.items():
        edges.append({
            'id': f"subnet_{subnet1}_{subnet2}",
            'from': group_nodes.get(subnet1),
            'to': group_nodes.get(subnet2),
            'label': f"{count} connections",
            'color': '#17a2b8',
            'width': min(2 + count * 0.5, 5),
            'dashes': False,
            'smooth': {'type': 'curvedCW', 'roundness': 0.3},
        })
    return jsonify({'nodes': nodes, 'edges': edges, 'timestamp': datetime.utcnow().isoformat()})

# ---------- 连接关系 API ----------
@topology_bp.route('/api/connections/<int:connection_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
@permission_required('topology:edit')
def api_connection_detail(connection_id):
    connection = ConnectionPath.query.get_or_404(connection_id)
    if request.method == 'GET':
        return jsonify({
            'id': connection.id,
            'source_device_id': connection.source_device_id,
            'source_device_name': connection.source_device.name if connection.source_device else None,
            'source_interface_id': connection.source_interface_id,
            'source_interface': connection.source_port,
            'source_port': connection.source_port,
            'target_device_id': connection.target_device_id,
            'target_device_name': connection.target_device.name if connection.target_device else None,
            'target_interface_id': connection.target_interface_id,
            'target_interface': connection.target_port,
            'target_port': connection.target_port,
            'connection_type': connection.connection_type,
            'link_status': connection.link_status,
            'bandwidth': connection.bandwidth,
            'vlan_id': connection.vlan_id,
            'media_type': connection.media_type,
            'discovered_by': connection.discovered_by,
            'discovery_time': connection.discovery_time.isoformat() if connection.discovery_time else None,
            'confidence': connection.confidence,
            'created_at': connection.created_at.isoformat() if connection.created_at else None,
        })
    elif request.method == 'PUT':
        data = request.get_json()
        if 'source_port' in data:
            connection.source_port = data['source_port']
        if 'target_port' in data:
            connection.target_port = data['target_port']
        if 'connection_type' in data:
            connection.connection_type = data['connection_type']
        if 'link_status' in data:
            connection.link_status = data['link_status']
        if 'bandwidth' in data:
            connection.bandwidth = data['bandwidth']
        if 'vlan_id' in data:
            connection.vlan_id = data['vlan_id']
        if 'media_type' in data:
            connection.media_type = data['media_type']
        if 'confidence' in data:
            connection.confidence = data['confidence']
        connection.updated_at = datetime.utcnow()
        db.session.commit()
        log_audit('update', 'connection', connection.id, f'更新连接关系 #{connection.id}',
                  details={'source_device_id': connection.source_device_id, 'target_device_id': connection.target_device_id},
                  user_id=current_user.id)
        return jsonify({'success': True, 'message': '连接关系更新成功'})
    elif request.method == 'DELETE':
        db.session.delete(connection)
        db.session.commit()
        log_audit('delete', 'connection', connection_id, f'删除连接关系 #{connection_id}',
                  user_id=current_user.id)
        return jsonify({'success': True, 'message': '连接关系删除成功'})

@topology_bp.route('/api/settings/save', methods=['POST'])
@login_required
@permission_required('topology:edit')
def api_save_settings():
    try:
        data = request.get_json()
        category = data.get('category', 'general')
        for setting_data in data.get('settings', []):
            setting_key = setting_data.get('key')
            setting_value = setting_data.get('value')
            setting_type = setting_data.get('type', 'string')
            setting = TopologySetting.query.filter_by(setting_key=setting_key, category=category).first()
            if not setting:
                setting = TopologySetting(
                    setting_key=setting_key,
                    setting_type=setting_type,
                    category=category,
                    created_by=current_user.username
                )
                db.session.add(setting)
            setting.setting_type = setting_type
            setting.set_value(setting_value)
            setting.updated_at = datetime.utcnow()
            setting.updated_by = current_user.username
        db.session.commit()
        log_audit('update', 'topology_setting', 0, '保存拓扑设置',
                  details={'category': category}, user_id=current_user.id)
        return jsonify({'success': True, 'message': '拓扑设置保存成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'保存设置失败: {str(e)}'}), 500

@topology_bp.route('/api/check-port-occupation', methods=['GET'])
@login_required
@permission_required('topology:view')
def api_check_port_occupation():
    device_id = request.args.get('device_id', type=int)
    interface_id = request.args.get('interface_id', type=int)
    if device_id is None or interface_id is None:
        return jsonify({'success': False, 'message': '缺少参数'}), 400
    interface = Interface.query.filter_by(id=interface_id, device_id=device_id).first()
    if not interface:
        return jsonify({'success': False, 'message': '接口不存在'}), 404
    occupied = ConnectionPath.query.filter(
        db.or_(
            db.and_(ConnectionPath.source_device_id == device_id, ConnectionPath.source_port == interface.name),
            db.and_(ConnectionPath.target_device_id == device_id, ConnectionPath.target_port == interface.name)
        )
    ).first() is not None
    return jsonify({'occupied': occupied})

@topology_bp.route('/add_connection', methods=['POST'])
@login_required
@permission_required('topology:edit')
def add_connection():
    try:
        source_device_id = request.form.get('source_device_id', type=int)
        target_device_id = request.form.get('target_device_id', type=int)
        source_port = request.form.get('source_port')
        target_port = request.form.get('target_port')
        connection_type = request.form.get('connection_type')
        link_status = request.form.get('link_status')
        bandwidth = request.form.get('bandwidth', type=int)
        media_type = request.form.get('media_type')
        vlan_id = request.form.get('vlan_id')
        discovered_by = request.form.get('discovered_by')
        description = request.form.get('description')

        if source_device_id == target_device_id:
            return jsonify({'success': False, 'message': '源设备和目标设备不能相同！'}), 400

        # 双向归一化：小 ID 永远放 source
        if source_device_id > target_device_id:
            source_device_id, target_device_id = target_device_id, source_device_id
            source_port, target_port = target_port, source_port

        # 检查该设备对是否已有链路
        existing_pair = ConnectionPath.query.filter(
            db.and_(
                ConnectionPath.source_device_id == source_device_id,
                ConnectionPath.target_device_id == target_device_id,
            )
        ).first()
        if existing_pair:
            return jsonify({'success': False,
                           'message': f'这两个设备之间已存在链路 ({existing_pair.source_port} ↔ {existing_pair.target_port})，请勿重复创建'}), 400

        # 检查源端口是否被占用
        existing_source = ConnectionPath.query.filter(
            ((ConnectionPath.source_device_id == source_device_id) & (ConnectionPath.source_port == source_port)) |
            ((ConnectionPath.target_device_id == source_device_id) & (ConnectionPath.target_port == source_port))
        ).first()
        if existing_source:
            return jsonify({'success': False, 'message': f'源设备端口 {source_port} 已被占用！'}), 400

        # 检查目标端口是否被占用
        existing_target = ConnectionPath.query.filter(
            ((ConnectionPath.source_device_id == target_device_id) & (ConnectionPath.source_port == target_port)) |
            ((ConnectionPath.target_device_id == target_device_id) & (ConnectionPath.target_port == target_port))
        ).first()
        if existing_target:
            return jsonify({'success': False, 'message': f'目标设备端口 {target_port} 已被占用！'}), 400

        connection = ConnectionPath(
            source_device_id=source_device_id,
            target_device_id=target_device_id,
            source_port=source_port,
            target_port=target_port,
            connection_type=connection_type,
            link_status=link_status,
            bandwidth=bandwidth,
            media_type=media_type,
            vlan_id=vlan_id,
            discovered_by=discovered_by,
            description=description
        )
        db.session.add(connection)
        db.session.commit()

        log_audit('create', 'connection', connection.id, '创建连接关系',
                  details={'source_device_id': source_device_id, 'target_device_id': target_device_id,
                           'source_port': source_port, 'target_port': target_port},
                  user_id=current_user.id)

        return jsonify({'success': True, 'message': '连接创建成功！'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'创建连接时发生错误: {str(e)}'}), 500

@topology_bp.route('/connections/<int:connection_id>/delete', methods=['POST'])
@login_required
@permission_required('topology:edit')
def delete_connection(connection_id):
    try:
        connection = ConnectionPath.query.get_or_404(connection_id)
        db.session.delete(connection)
        db.session.commit()
        log_audit('delete', 'connection', connection_id, f'删除连接关系 #{connection_id}',
                  user_id=current_user.id)
        return jsonify({'success': True, 'message': '连接删除成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除连接时发生错误: {str(e)}'}), 500

# ====================== 批量删除 & 导出 API ======================

@topology_bp.route('/connections/batch_delete', methods=['POST'])
@login_required
@permission_required('topology:edit')
def batch_delete_connections():
    """批量删除连接"""
    try:
        data = request.get_json()
        if not data or 'ids' not in data:
            return jsonify({'success': False, 'message': '请提供要删除的连接ID列表'}), 400
        
        ids = data['ids']
        if not isinstance(ids, list) or len(ids) == 0:
            return jsonify({'success': False, 'message': '连接ID列表不能为空'}), 400
        
        # 查询所有存在的连接
        connections = ConnectionPath.query.filter(ConnectionPath.id.in_(ids)).all()
        if not connections:
            return jsonify({'success': False, 'message': '未找到任何匹配的连接'}), 404
        
        deleted_count = 0
        for conn in connections:
            db.session.delete(conn)
            deleted_count += 1
        
        db.session.commit()
        log_audit('delete', 'connection', 0, f'批量删除 {deleted_count} 条连接关系',
                  details={'ids': ids, 'deleted_count': deleted_count},
                  user_id=current_user.id)
        return jsonify({'success': True, 'message': f'成功删除 {deleted_count} 条连接', 'deleted_count': deleted_count})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'批量删除失败: {str(e)}'}), 500


# ---------- 接口管理 API ----------
@topology_bp.route('/api/interface/stats')
@login_required
@permission_required('topology:view')
def api_interface_stats():
    status_stats = db.session.query(Interface.status, func.count(Interface.id).label('count')).group_by(Interface.status).all()
    type_stats = db.session.query(Interface.type, func.count(Interface.id).label('count')).group_by(Interface.type).all()
    high_util_interfaces = Interface.query.filter(
        db.or_(Interface.in_utilization > 80, Interface.out_utilization > 80)
    ).limit(10).all()
    return jsonify({
        'status_stats': {status: count for status, count in status_stats},
        'type_stats': {type_: count for type_, count in type_stats},
        'high_util_interfaces': [{'device': iface.device.name, 'interface': iface.name,
                                   'in_utilization': iface.in_utilization, 'out_utilization': iface.out_utilization,
                                   'status': iface.status} for iface in high_util_interfaces]
    })

@topology_bp.route('/api/interfaces', methods=['GET'])
@login_required
@permission_required('topology:view')
def get_interfaces():
    interfaces = Interface.query.all()
    return jsonify([interface.to_dict() for interface in interfaces])

@topology_bp.route('/api/interfaces/<int:interface_id>', methods=['PUT', 'DELETE'])
@login_required
@permission_required('topology:edit')
def api_interface_detail(interface_id):
    interface = Interface.query.get_or_404(interface_id)
    if request.method == 'PUT':
        data = request.get_json()
        allowed_fields = ['name', 'type', 'status', 'speed', 'ip_address', 'subnet_mask', 'mac_address', 'vlan', 'description', 'mtu']
        for field in allowed_fields:
            if field in data:
                value = data[field]
                if field == 'name' and value:
                    existing = Interface.query.filter(
                        Interface.device_id == interface.device_id,
                        Interface.name == value,
                        Interface.id != interface.id
                    ).first()
                    if existing:
                        return jsonify({'success': False, 'message': f'接口名称 "{value}" 在该设备中已存在'}), 400
                setattr(interface, field, value)
        interface.updated_at = datetime.utcnow()
        db.session.commit()
        log_audit('update', 'interface', interface.id, f'更新接口 #{interface.id}',
                  details={'device_id': interface.device_id, 'name': interface.name},
                  user_id=current_user.id)
        return jsonify({'success': True, 'message': '接口更新成功'})
    elif request.method == 'DELETE':
        db.session.delete(interface)
        db.session.commit()
        log_audit('delete', 'interface', interface_id, f'删除接口 #{interface_id}',
                  details={'device_id': interface.device_id, 'name': interface.name},
                  user_id=current_user.id)
        return jsonify({'success': True, 'message': '接口删除成功'})

@topology_bp.route('/api/interfaces/batch', methods=['DELETE'])
@login_required
@permission_required('topology:edit')
def batch_delete_interfaces():
    data = request.get_json()
    if not data or 'interface_ids' not in data:
        return jsonify({'success': False, 'message': '请提供要删除的接口ID列表'}), 400
    ids = data['interface_ids']
    if not isinstance(ids, list) or len(ids) == 0:
        return jsonify({'success': False, 'message': '接口ID列表不能为空'}), 400
    interfaces = Interface.query.filter(Interface.id.in_(ids)).all()
    if not interfaces:
        return jsonify({'success': False, 'message': '未找到任何匹配的接口'}), 404
    deleted_count = 0
    for interface in interfaces:
        db.session.delete(interface)
        deleted_count += 1
    db.session.commit()
    log_audit('delete', 'interface', 0, f'批量删除 {deleted_count} 个接口',
              details={'interface_ids': data.get('interface_ids', []), 'deleted_count': deleted_count},
              user_id=current_user.id)
    return jsonify({'success': True, 'message': f'成功删除 {deleted_count} 个接口', 'deleted_count': deleted_count})

@topology_bp.route('/api/interfaces/device/<int:device_id>', methods=['GET'])
@login_required
@permission_required('topology:view')
def api_get_device_interfaces(device_id):
    device = Device.query.get_or_404(device_id)
    interfaces = Interface.query.filter_by(device_id=device_id).all()

    # 对端信息：本设备端口名 -> 对端设备名/对端端口（来自连接关系，批量查询一次）
    peer_by_port = {}
    conns = ConnectionPath.query.filter(
        or_(
            ConnectionPath.source_device_id == device_id,
            ConnectionPath.target_device_id == device_id,
        )
    ).all()
    peer_dev_ids = set()
    for cp in conns:
        if cp.source_device_id == device_id:
            port, peer_dev_id, peer_iface = cp.source_port, cp.target_device_id, cp.target_port
        else:
            port, peer_dev_id, peer_iface = cp.target_port, cp.source_device_id, cp.source_port
        if not port:
            continue
        peer_dev_ids.add(peer_dev_id)
        peer_by_port[port] = (peer_dev_id, peer_iface)
    peer_names = {}
    if peer_dev_ids:
        for pd in Device.query.filter(Device.id.in_(peer_dev_ids)).all():
            peer_names[pd.id] = pd.name

    interface_list = []
    for iface in interfaces:
        peer_dev_id, peer_iface = peer_by_port.get(iface.name, (None, None))
        interface_list.append({
            'id': iface.id,
            'name': iface.name,
            'type': getattr(iface, 'type', 'Ethernet'),
            'description': iface.description,
            'admin_status': iface.admin_status,
            'oper_status': iface.oper_status,
            'status': iface.admin_status or iface.oper_status or 'unknown',
            'peer_device': peer_names.get(peer_dev_id) if peer_dev_id else None,
            'peer_interface': peer_iface,
            'speed': iface.speed,
            'mtu': iface.mtu,
            'mac_address': iface.mac_address,
            'ip_address': iface.ip_address,
            'subnet_mask': iface.subnet_mask,
            'in_utilization': iface.in_utilization,
            'out_utilization': iface.out_utilization,
            'created_at': iface.created_at.isoformat() if iface.created_at else None,
            'updated_at': iface.updated_at.isoformat() if iface.updated_at else None
        })
    return jsonify({'success': True, 'device_id': device_id, 'device_name': device.name,
                    'interface_count': len(interface_list), 'interfaces': interface_list})

@topology_bp.route('/api/interfaces/snmp_test', methods=['POST', 'GET'])
@login_required
@permission_required('topology:edit')
def api_snmp_test():
    if request.method == 'GET':
        return jsonify({'success': True, 'message': 'SNMP测试API已就绪', 'supported_methods': ['POST']})
    data = request.get_json()
    device_id = data.get('device_id')
    snmp_community = data.get('snmp_community', 'public')
    snmp_version = data.get('snmp_version', '2c')
    snmp_port = data.get('snmp_port', 161)
    device = Device.query.get(device_id)
    if not device:
        return jsonify({'success': False, 'message': '设备不存在'}), 404
    target_ip = device.management_ip or device.ip_address
    if not target_ip:
        return jsonify({'success': False, 'message': '设备无IP地址'}), 400
    try:
        iterator = getCmd(
            SnmpEngine(),
            CommunityData(snmp_community, mpModel=1 if snmp_version == '1' else 0),
            UdpTransportTarget((target_ip, snmp_port), timeout=3, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity('SNMPv2-MIB', 'sysDescr', 0))
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        if errorIndication:
            return jsonify({'success': False, 'message': str(errorIndication)})
        elif errorStatus:
            return jsonify({'success': False, 'message': f'SNMP错误: {errorStatus}'})
        else:
            system_description = str(varBinds[0][1])
            return jsonify({'success': True, 'message': 'SNMP连接成功', 'system_description': system_description})
    except Exception as e:
        return jsonify({'success': False, 'message': f'连接异常: {str(e)}'}), 500

@topology_bp.route('/api/interfaces/snmp_discover', methods=['POST'])
@login_required
@permission_required('topology:edit')
def api_snmp_discover_interfaces():
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        snmp_community = data.get('snmp_community', 'public')
        snmp_version = data.get('snmp_version', '2c')
        snmp_port = data.get('snmp_port', 161)
        auto_save = data.get('auto_save', False)

        if not device_id:
            return jsonify({'success': False, 'message': '设备ID不能为空'}), 400
        device = Device.query.get(device_id)
        if not device:
            return jsonify({'success': False, 'message': '设备不存在'}), 404
        target_ip = device.management_ip or device.ip_address
        if not target_ip:
            return jsonify({'success': False, 'message': '设备没有IP地址'}), 400

        discovered_interfaces = discover_interfaces_via_snmp(target_ip, snmp_community)
        saved_interfaces = []
        saved_count = 0
        updated_count = 0
        if auto_save and discovered_interfaces:
            for iface in discovered_interfaces:
                existing = Interface.query.filter_by(device_id=device_id, name=iface['name']).first()
                idx = iface.get('index')
                oper = iface.get('oper_status', 'unknown')
                admin = iface.get('admin_status', 'unknown')
                if existing:
                    changed = False
                    if oper and existing.oper_status != oper:
                        existing.oper_status = oper
                        changed = True
                    if admin and existing.admin_status != admin:
                        existing.admin_status = admin
                        changed = True
                    if idx and existing.ifindex != int(idx) and existing.ifindex is None:
                        existing.ifindex = int(idx)
                        changed = True
                    if idx and existing.snmp_index != int(idx):
                        existing.snmp_index = int(idx)
                        changed = True
                    if changed:
                        existing.updated_at = datetime.utcnow()
                        updated_count += 1
                else:
                    new_iface = Interface(
                        device_id=device_id,
                        name=iface['name'],
                        ifindex=int(idx) if idx else None,
                        snmp_index=int(idx) if idx else None,
                        type='Ethernet',
                        speed=iface.get('speed', 0),
                        mtu=iface.get('mtu', 1500),
                        mac_address=iface.get('mac_address', ''),
                        admin_status=admin,
                        oper_status=oper
                    )
                    db.session.add(new_iface)
                    saved_interfaces.append(iface['name'])
            db.session.commit()
            saved_count = len(saved_interfaces)
            log_audit('update', 'interface', 0, f'SNMP发现并同步 {saved_count} 个新接口、{updated_count} 个已有接口',
                      details={'device_id': device_id, 'saved_count': saved_count, 'updated_count': updated_count},
                      user_id=current_user.id)

        return jsonify({
            'success': True,
            'message': f'成功发现 {len(discovered_interfaces)} 个接口',
            'device_name': device.name,
            'discovered_count': len(discovered_interfaces),
            'saved_count': saved_count,
            'updated_count': updated_count,
            'interfaces': discovered_interfaces[:20],
            'auto_saved': auto_save
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'SNMP发现失败: {str(e)}'}), 500

@topology_bp.route('/api/interfaces/refresh', methods=['POST'])
@login_required
@permission_required('topology:edit')
def refresh_interfaces():
    return jsonify({'success': True, 'message': '刷新成功'})


@topology_bp.route('/api/interfaces/<int:interface_id>/refresh', methods=['POST'])
@login_required
@permission_required('topology:view')
def api_refresh_single_interface(interface_id):
    """重新通过 SNMP 获取单个接口的实时状态并更新"""
    interface = Interface.query.get_or_404(interface_id)
    device = Device.query.get(interface.device_id)
    if not device:
        return jsonify({'success': False, 'message': '接口没有关联设备'}), 404
    ip = device.management_ip or device.ip_address
    if not ip:
        return jsonify({'success': False, 'message': '设备没有管理 IP，无法刷新'}), 400
    community = getattr(device, 'snmp_community', 'public')
    version = getattr(device, 'snmp_version', '2c')
    idx = interface.ifindex or interface.snmp_index
    if idx:
        try:
            oper_raw = snmp_get(ip, community, version, f'.1.3.6.1.2.1.2.2.1.8.{idx}', timeout=3)
            adm_raw = snmp_get(ip, community, version, f'.1.3.6.1.2.1.2.2.1.7.{idx}', timeout=3)
            oper = parse_if_status(oper_raw) if oper_raw is not None else None
            adm = parse_if_status(adm_raw) if adm_raw is not None else None
            if oper in ('up', 'down'):
                interface.oper_status = oper
            if adm in ('up', 'down'):
                interface.admin_status = adm
        except Exception as e:
            logger.error(f"刷新接口 {interface.name} 失败: {e}")
    new_status = interface.admin_status or interface.oper_status or 'unknown'
    interface.status = new_status
    interface.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({
        'success': True,
        'message': '接口数据刷新成功',
        'interface': {
            'id': interface.id,
            'device_id': device.id,
            'device_name': device.name,
            'device_ip': device.ip_address or device.management_ip or 'N/A',
            'interface_name': interface.name,
            'interface_type': interface.type or 'Ethernet',
            'status': new_status,
            'oper_status': interface.oper_status,
            'admin_status': interface.admin_status,
            'speed': interface.speed,
            'mtu': interface.mtu,
            'description': interface.description or '',
            'mac_address': interface.mac_address or '',
            'ip_address': interface.ip_address or '',
            'subnet_mask': interface.subnet_mask or '',
            'vlan': interface.vlan,
            'in_utilization': interface.in_utilization or 0,
            'out_utilization': interface.out_utilization or 0,
            'last_seen': interface.updated_at.strftime('%Y-%m-%d %H:%M:%S') if interface.updated_at else 'N/A'
        }
    })

@topology_bp.route('/api/interfaces/manual', methods=['POST'])
@login_required
@permission_required('topology:edit')
def api_manual_create_interface():
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        name = data.get('name')
        interface_type = data.get('type', 'Ethernet')
        status = data.get('status', 'down')

        if not device_id or not name:
            return jsonify({'success': False, 'message': '设备ID和接口名称不能为空'}), 400
        device = Device.query.get(device_id)
        if not device:
            return jsonify({'success': False, 'message': '设备不存在'}), 404
        existing = Interface.query.filter_by(device_id=device_id, name=name).first()
        if existing:
            return jsonify({'success': False, 'message': f'接口 {name} 已存在'}), 400

        interface = Interface(
            device_id=device_id,
            name=name,
            type=interface_type,
            description=data.get('description', ''),
            admin_status=status,
            oper_status=status,
            speed=data.get('speed', 1000000000),
            mtu=data.get('mtu', 1500),
            mac_address=data.get('mac_address', ''),
            ip_address=data.get('ip_address', ''),
            subnet_mask=data.get('subnet_mask', ''),
            vlan=data.get('vlan', '')
        )
        db.session.add(interface)
        db.session.commit()
        log_audit('create', 'interface', interface.id, f'手动创建接口 {name}',
                  details={'device_id': device_id, 'interface_name': name},
                  user_id=current_user.id)
        return jsonify({'success': True, 'message': f'成功创建接口 {name}', 'interface_id': interface.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'创建接口失败: {str(e)}'}), 500

@topology_bp.route('/api/interfaces/batch', methods=['POST'])
@login_required
@permission_required('topology:edit')
def api_batch_create_interfaces():
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        pattern = data.get('pattern')
        slot = data.get('slot', 0)
        start_port = data.get('start_port', 1)
        end_port = data.get('end_port', 48)
        default_status = data.get('default_status', 'down')
        default_speed = data.get('default_speed', 1000000000)

        device = Device.query.get(device_id)
        if not device:
            return jsonify({'success': False, 'message': '设备不存在'}), 404

        existing_interfaces = Interface.query.filter_by(device_id=device_id).all()
        existing_names = {iface.name for iface in existing_interfaces}

        created = []
        skipped = []
        for port in range(start_port, end_port + 1):
            interface_name = pattern.replace('{slot}', str(slot)).replace('{port}', str(port))
            if interface_name in existing_names:
                skipped.append(interface_name)
            else:
                admin_status = 'up' if default_status == 'up' else 'down'
                oper_status = admin_status
                interface = Interface(
                    device_id=device_id,
                    name=interface_name,
                    type='Ethernet',
                    description=f'批量创建的接口 {interface_name}',
                    admin_status=admin_status,
                    oper_status=oper_status,
                    speed=default_speed,
                    mtu=1500
                )
                db.session.add(interface)
                created.append(interface_name)
                existing_names.add(interface_name)

        db.session.commit()
        log_audit('create', 'interface', 0, f'批量创建 {len(created)} 个接口',
                  details={'device_id': device_id, 'created_count': len(created), 'skipped_count': len(skipped)},
                  user_id=current_user.id)
        return jsonify({
            'success': True,
            'message': f'批量创建完成，创建 {len(created)} 个，跳过 {len(skipped)} 个',
            'created_count': len(created),
            'skipped_count': len(skipped)
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'批量创建失败: {str(e)}'}), 500

@topology_bp.route('/api/interfaces/check_db', methods=['GET'])
@login_required
@permission_required('topology:view')
def api_check_database():
    try:
        db.session.execute(text('SELECT 1'))
        device_count = Device.query.count()
        interface_count = Interface.query.count()
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()
        interface_columns = []
        if 'interfaces' in table_names:
            interface_columns = [{'name': col['name'], 'type': str(col['type'])} for col in inspector.get_columns('interfaces')]
        return jsonify({
            'success': True,
            'database_status': 'connected',
            'device_count': device_count,
            'interface_count': interface_count,
            'table_names': table_names,
            'interface_columns': interface_columns
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'数据库检查失败: {str(e)}'}), 500

# ---------- 拓扑发现 API ----------

@topology_bp.route('/api/discovery/start', methods=['POST'])
@login_required
@permission_required('topology:edit')
def api_start_discovery():
    """创建新的发现任务（支持两种模式）"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '无效的请求数据'}), 400

    # 通用字段
    name = data.get('task_name')
    if not name:
        return jsonify({'success': False, 'message': '任务名称不能为空'}), 400

    task = DiscoveryTask(
        name=name,
        description=data.get('description', ''),
        discovery_mode=data.get('discovery_mode', 'protocol'),
        schedule_type=data.get('schedule_type', 'manual'),
        interval_seconds=data.get('interval_seconds', 3600),
        cron_expression=data.get('cron_expression'),
        max_threads=data.get('max_threads', 10),
        scan_timeout=data.get('scan_timeout', 30),
        rate_limit=data.get('rate_limit', 100),
        auto_save=data.get('auto_save', True),
        overwrite_existing=data.get('overwrite_existing', False),
        create_missing=data.get('create_missing', True),
        status='idle',
        enabled=True,
        created_by=current_user.username
    )

    mode = data.get('discovery_mode')
    if mode == 'protocol':
        # 协议发现
        task.discovery_type = data.get('discovery_type', 'custom')
        task.target_type = data.get('target_type', 'subnet')
        task.use_lldp = data.get('use_lldp', True)
        task.use_cdp = data.get('use_cdp', True)
        task.use_snmp = data.get('use_snmp', True)
        task.snmp_community = data.get('snmp_community', 'public')
        task.snmp_version = data.get('snmp_version', 2)
        task.snmp_timeout = data.get('snmp_timeout', 5)
        task.snmp_retries = data.get('snmp_retries', 3)
        task.max_depth = data.get('max_depth', 3)
        task.max_hops = data.get('max_hops', 10)
        # 保存目标值
        target_value = data.get('target_value', {})
        task.set_target_value(target_value)
    elif mode == 'ipmac':
        # IP/MAC 发现
        core_device_id = data.get('core_device_id')
        if not core_device_id:
            return jsonify({'success': False, 'message': '必须选择核心交换机'}), 400
        core_device = Device.query.get(core_device_id)
        if not core_device:
            return jsonify({'success': False, 'message': '核心交换机不存在'}), 400
        task.core_device_id = core_device_id
        access_ids = data.get('access_device_ids', [])
        for aid in access_ids:
            if not Device.query.get(aid):
                return jsonify({'success': False, 'message': f'接入交换机 ID {aid} 不存在'}), 400
        task.set_access_device_ids(access_ids)
        
        # --- 关键修复：为 NOT NULL 字段设置值 ---
        task.discovery_type = 'ipmac'          # 设置一个明确的值
        task.target_type = 'ipmac'              # 设置目标类型
        # -------------------------------------
        
        task.set_target_value({'core_device_id': core_device_id, 'access_device_ids': access_ids})
        # 清空协议相关字段
        task.use_lldp = False
        task.use_cdp = False
        task.use_snmp = False
    else:
        return jsonify({'success': False, 'message': '未知的发现模式'}), 400

    db.session.add(task)
    db.session.commit()
    log_audit('create', 'discovery_task', task.id, f'创建发现任务 {name}',
              details={'discovery_mode': mode, 'task_name': name},
              user_id=current_user.id)

    # 如果选择了间隔执行或 Cron 表达式，注册调度器任务
    from scheduler import schedule_discovery_task, schedule_discovery_task_cron
    if task.schedule_type == 'interval':
        schedule_discovery_task(task.id, task.interval_seconds or 3600)
    elif task.schedule_type == 'cron' and task.cron_expression:
        schedule_discovery_task_cron(task.id, task.cron_expression)

    return jsonify({'success': True, 'message': '发现任务创建成功', 'task_id': task.id})



@topology_bp.route('/api/discovery/tasks', methods=['GET'])
@login_required
@permission_required('topology:view')
def api_get_discovery_tasks():
    from scheduler import get_discovery_job_info

    tasks = DiscoveryTask.query.order_by(DiscoveryTask.created_at.desc()).all()
    task_list = []
    for task in tasks:
        task_dict = task.to_dict()
        if task.discovery_mode == 'ipmac':
            task_dict['core_device_name'] = get_device_name(task.core_device_id)
            task_dict['access_device_count'] = len(task.get_access_device_ids())

        # 附加调度器信息
        job_info = get_discovery_job_info(task.id)
        if job_info:
            task_dict['next_run_time'] = job_info['next_run_time']
            task_dict['schedule_status'] = 'scheduled'
        elif task.schedule_type in ('interval', 'cron') and task.enabled:
            task_dict['schedule_status'] = 'not_scheduled'
        else:
            task_dict['schedule_status'] = 'manual'

        task_list.append(task_dict)
    return jsonify({'success': True, 'tasks': task_list})


@topology_bp.route('/api/discovery/scheduler/jobs', methods=['GET'])
@login_required
@permission_required('topology:view')
def api_scheduler_jobs():
    """调试接口：查看当前调度器中所有任务"""
    from scheduler import get_scheduler
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            'job_id': job.id,
            'name': job.name,
            'func': str(job.func_ref) if hasattr(job, 'func_ref') else str(job.func),
            'trigger': str(job.trigger),
            'next_run_time': str(job.next_run_time) if job.next_run_time else None,
            'pending': job.pending,
        })
    return jsonify({
        'success': True,
        'scheduler_running': scheduler.running,
        'jobs': jobs,
        'job_count': len(jobs)
    })


@topology_bp.route('/api/discovery/tasks/<int:task_id>/run', methods=['POST'])
@login_required
@permission_required('topology:edit')
def api_run_task(task_id):
    task = DiscoveryTask.query.get_or_404(task_id)
    if task.status == 'running':
        return jsonify({'success': False, 'message': '任务已在运行中'}), 400
    if task.status == 'paused':
        task.status = 'running'
        db.session.commit()
        log_audit('update', 'discovery_task', task_id, f'恢复运行发现任务 #{task_id}',
                  user_id=current_user.id)
        app = current_app._get_current_object()
        stop_events[task.id] = threading.Event()
        discovery_executor.submit(background_discovery, task.id, app)
        return jsonify({'success': True, 'message': '任务已恢复运行'})

    task.status = 'running'
    task.progress = 0
    db.session.commit()
    log_audit('execute', 'discovery_task', task_id, f'启动发现任务 #{task_id}',
              user_id=current_user.id)
    app = current_app._get_current_object()
    stop_events[task.id] = threading.Event()
    discovery_executor.submit(background_discovery, task.id, app)
    return jsonify({'success': True, 'message': '任务已启动'})


@topology_bp.route('/api/discovery/tasks/<int:task_id>/resume', methods=['POST'])
@login_required
@permission_required('topology:edit')
def api_resume_task(task_id):
    task = DiscoveryTask.query.get_or_404(task_id)
    if task.status != 'paused':
        return jsonify({'success': False, 'message': '任务未处于暂停状态'}), 400
    task.status = 'running'
    db.session.commit()
    log_audit('update', 'discovery_task', task_id, f'恢复发现任务 #{task_id}',
              user_id=current_user.id)
    app = current_app._get_current_object()
    stop_events[task.id] = threading.Event()
    discovery_executor.submit(background_discovery, task.id, app)
    return jsonify({'success': True, 'message': '任务已恢复'})

@topology_bp.route('/api/discovery/tasks/<int:task_id>/stop', methods=['POST'])
@login_required
@permission_required('topology:edit')
def api_stop_task(task_id):
    task = DiscoveryTask.query.get_or_404(task_id)
    if task.status != 'running':
        return jsonify({'success': False, 'message': '任务未在运行'}), 400
    if task_id in stop_events:
        stop_events[task_id].set()
    task.status = 'paused'
    db.session.commit()
    log_audit('update', 'discovery_task', task_id, f'暂停发现任务 #{task_id}',
              user_id=current_user.id)
    return jsonify({'success': True, 'message': '任务已暂停'})


@topology_bp.route('/api/discovery/recent_results', methods=['GET'])
@login_required
@permission_required('topology:view')
def api_recent_results():
    results = DiscoveryResult.query.order_by(DiscoveryResult.discovered_at.desc()).limit(20).all()
    result_list = []
    for r in results:
        result_list.append({
            'id': r.id,
            'target_ip': r.target_ip,
            'target_hostname': r.target_hostname,
            'discovered_ip': r.discovered_ip,
            'discovered_hostname': r.discovered_hostname,
            'discovered_device_type': r.discovered_device_type,
            'discovery_protocol': r.discovery_protocol,
            'local_interface': r.local_interface,
            'remote_interface': r.remote_interface,
            'is_new_device': r.is_new_device,
            'is_new_connection': r.is_new_connection,
            'verified': r.verified,
            'confidence': r.confidence,
            'discovered_at': r.discovered_at.isoformat() if r.discovered_at else None
        })
    return jsonify({'success': True, 'results': result_list})

@topology_bp.route('/api/discovery/settings', methods=['GET'])
@login_required
@permission_required('topology:view')
def api_discovery_settings():
    settings = TopologySetting.query.filter_by(category='discovery').all()
    settings_dict = {s.setting_key: s.get_value() for s in settings}
    return jsonify({'success': True, 'settings': settings_dict})

@topology_bp.route('/api/discovery/tasks/running', methods=['GET'])
@login_required
@permission_required('topology:view')
def api_running_tasks():
    tasks = DiscoveryTask.query.filter(DiscoveryTask.status.in_(['running', 'paused'])).all()
    task_list = []
    for task in tasks:
        total_results = DiscoveryResult.query.filter_by(task_id=task.id).count()
        new_devices = DiscoveryResult.query.filter_by(task_id=task.id, is_new_device=True).count()
        task_list.append({
            'id': task.id,
            'status': task.status,
            'status_display': task.status.capitalize(),
            'progress': task.progress,
            'stats': {'total': total_results, 'new_devices': new_devices}
        })
    return jsonify({'success': True, 'tasks': task_list})

@topology_bp.route('/api/discovery/results/<int:task_id>')
@login_required
@permission_required('topology:view')
def api_discovery_results(task_id):
    task = DiscoveryTask.query.get_or_404(task_id)
    results = DiscoveryResult.query.filter_by(task_id=task_id).order_by(DiscoveryResult.discovered_at.desc()).all()
    return jsonify({
        'task': task.to_dict(),
        'results': [result.to_dict() for result in results],
        'total': len(results),
        'timestamp': datetime.utcnow().isoformat()
    })

# ---------- 其他路由 ----------
@topology_bp.route('/create_layout', methods=['POST'])
@login_required
@permission_required('topology:edit')
def create_layout():
    name = request.form.get('name')
    layout_type = request.form.get('layout_type')
    description = request.form.get('description')
    is_default = request.form.get('is_default') == 'on'
    enabled = request.form.get('enabled') == 'on'
    node_spacing = request.form.get('node_spacing')
    level_spacing = request.form.get('level_spacing')
    direction = request.form.get('direction')
    layout_data = {
        'node_spacing': int(node_spacing) if node_spacing else 100,
        'level_spacing': int(level_spacing) if level_spacing else 150,
        'direction': direction if direction else 'LR',
    }
    layout = TopologyLayout(
        name=name,
        layout_type=layout_type,
        description=description,
        is_default=is_default,
        enabled=enabled,
        layout_data=json.dumps(layout_data, ensure_ascii=False),
        link_routing='straight',
        grid_enabled=True,
        grid_size=20,
        snap_to_grid=True,
        zoom_level=1.0,
        center_x=0,
        center_y=0,
        show_grid=True,
        show_labels=True,
    )
    db.session.add(layout)
    db.session.commit()
    log_audit('create', 'topology_layout', layout.id, f'创建布局 {name}',
              details={'layout_type': layout_type},
              user_id=current_user.id)
    flash('布局创建成功', 'success')
    return redirect(url_for('topology.topology_settings'))

@topology_bp.route('/layouts/<int:layout_id>/apply', methods=['POST'])
@login_required
@permission_required('topology:edit')
def apply_layout(layout_id):
    try:
        layout = TopologyLayout.query.get_or_404(layout_id)
        return jsonify({'success': True, 'message': '布局应用成功', 'layout_name': layout.name})
    except Exception as e:
        return jsonify({'success': False, 'message': f'应用布局时发生错误: {str(e)}'}), 500

@topology_bp.route('/layouts/<int:layout_id>/export')
@login_required
@permission_required('topology:view')
def export_layout(layout_id):
    try:
        layout = TopologyLayout.query.get_or_404(layout_id)
        layout_data = {
            'name': layout.name,
            'layout_type': layout.layout_type,
            'description': layout.description,
            'node_spacing': layout.node_spacing,
            'level_spacing': layout.level_spacing,
            'direction': layout.direction,
            'is_default': layout.is_default,
            'enabled': layout.enabled,
            'created_at': layout.created_at.isoformat() if layout.created_at else None,
            'exported_at': datetime.utcnow().isoformat()
        }
        from flask import make_response
        response = make_response(json.dumps(layout_data, indent=2))
        response.headers['Content-Type'] = 'application/json'
        response.headers['Content-Disposition'] = f'attachment; filename=layout-{layout.name}-{datetime.utcnow().strftime("%Y%m%d")}.json'
        return response
    except Exception as e:
        flash(f'导出布局时发生错误: {str(e)}', 'error')
        return redirect(url_for('topology.topology_settings'))

@topology_bp.route('/settings/export')
@login_required
@permission_required('topology:view')
def export_settings():
    try:
        settings = TopologySetting.query.all()
        settings_data = {}
        for setting in settings:
            settings_data[setting.setting_key] = {
                'value': setting.setting_value,
                'data_type': setting.data_type,
                'category': setting.category,
                'description': setting.description,
                'display_name': setting.display_name,
                'min_value': setting.min_value,
                'max_value': setting.max_value,
                'options': setting.options,
                'updated_at': setting.updated_at.isoformat() if setting.updated_at else None
            }
        return jsonify(settings_data)
    except Exception as e:
        return jsonify({'success': False, 'message': f'导出设置时发生错误: {str(e)}'}), 500

@topology_bp.route('/settings/import', methods=['POST'])
@login_required
@permission_required('topology:edit')
def import_settings():
    try:
        data = request.get_json()
        if not data or 'settings' not in data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400
        settings_data = data['settings']
        overwrite = data.get('overwrite', False)
        imported_count = 0
        for key, setting_info in settings_data.items():
            setting = TopologySetting.query.filter_by(setting_key=key).first()
            if setting and overwrite:
                setting.setting_value = str(setting_info.get('value', ''))
                setting.data_type = setting_info.get('data_type', 'string')
                setting.description = setting_info.get('description')
                setting.display_name = setting_info.get('display_name')
                setting.updated_at = datetime.utcnow()
                imported_count += 1
            elif not setting:
                new_setting = TopologySetting(
                    setting_key=key,
                    setting_value=str(setting_info.get('value', '')),
                    data_type=setting_info.get('data_type', 'string'),
                    category=setting_info.get('category', 'General'),
                    description=setting_info.get('description'),
                    display_name=setting_info.get('display_name')
                )
                db.session.add(new_setting)
                imported_count += 1
        db.session.commit()
        log_audit('update', 'topology_setting', 0, f'导入 {imported_count} 个设置',
                  details={'imported_count': imported_count, 'overwrite': overwrite},
                  user_id=current_user.id)
        return jsonify({'success': True, 'message': f'成功导入 {imported_count} 个设置', 'imported_count': imported_count})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'导入设置时发生错误: {str(e)}'}), 500

# ---------- 初始化 ----------
def init_topology_settings():
    """初始化默认拓扑设置（保持原有）"""
    default_settings = [
        {'key': 'discovery_enabled', 'value': True, 'type': 'boolean', 'category': 'discovery', 'description': '是否启用自动拓扑发现'},
        {'key': 'discovery_interval', 'value': 3600, 'type': 'number', 'category': 'discovery', 'description': '自动发现间隔（秒）'},
        {'key': 'discovery_max_depth', 'value': 3, 'type': 'number', 'category': 'discovery', 'description': '最大发现深度'},
        {'key': 'snmp_default_community', 'value': 'public', 'type': 'string', 'category': 'discovery', 'description': 'SNMP默认团体名'},
        {'key': 'physical_layout_type', 'value': 'hierarchical', 'type': 'string', 'category': 'visualization', 'description': '物理拓扑布局类型'},
        {'key': 'logical_layout_type', 'value': 'circular', 'type': 'string', 'category': 'visualization', 'description': '逻辑拓扑布局类型'},
        {'key': 'show_device_labels', 'value': True, 'type': 'boolean', 'category': 'visualization', 'description': '是否显示设备标签'},
        {'key': 'show_connection_labels', 'value': True, 'type': 'boolean', 'category': 'visualization', 'description': '是否显示连接标签'},
        {'key': 'auto_refresh_interval', 'value': 30, 'type': 'number', 'category': 'visualization', 'description': '自动刷新间隔（秒）'},
        {'key': 'export_format', 'value': 'json', 'type': 'string', 'category': 'export', 'description': '默认导出格式'},
        {'key': 'export_include_devices', 'value': True, 'type': 'boolean', 'category': 'export', 'description': '导出时包含设备信息'},
        {'key': 'export_include_connections', 'value': True, 'type': 'boolean', 'category': 'export', 'description': '导出时包含连接信息'},
    ]
    for setting_data in default_settings:
        setting = TopologySetting.query.filter_by(setting_key=setting_data['key'], category=setting_data['category']).first()
        if not setting:
            setting = TopologySetting(
                setting_key=setting_data['key'],
                setting_type=setting_data['type'],
                category=setting_data['category'],
                description=setting_data['description'],
                is_default=True,
                created_by='system'
            )
            setting.set_value(setting_data['value'])
            db.session.add(setting)
    db.session.commit()




# ---------- 辅助函数 ----------
def get_current_user():
    """获取当前登录用户（示例，根据实际认证系统修改）"""
    from flask_login import current_user
    return current_user


def validate_csrf_token():
    """验证 CSRF token（根据实际实现调整）"""
    # 例如从请求头获取 X-CSRFToken，并与 session 中的 token 比对
    # 此处略，可在具体路由中通过 @csrf.exempt 跳过，或统一验证
    pass



# ---------- API 1: 获取设备接口列表 ----------
@topology_bp.route('/api/interfaces/device/<int:device_id>')
@login_required
@permission_required('topology:view')
def get_device_interfaces(device_id):
    """
    GET /topology/api/interfaces/device/<id>
    返回指定设备的所有接口
    """
    device = Device.query.get(device_id)
    if not device:
        return jsonify({'success': False, 'message': '设备不存在'}), 404

    interfaces = Interface.query.filter_by(device_id=device_id).all()
    data = [{
        'id': iface.id,
        'name': iface.name,
        'description': iface.description,
    } for iface in interfaces]

    return jsonify({'success': True, 'interfaces': data})


# ---------- API 2: 检查端口占用（支持排除自身）----------
@topology_bp.route('/api/check-port-occupation')
@login_required
@permission_required('topology:view')
def check_port_occupation():
    """
    GET /topology/api/check-port-occupation
    参数:
        device_id: int (必须)
        interface_id: int (必须)
        exclude_connection: int (可选) 排除的连接ID
    返回:
        {"occupied": true/false}
    """
    device_id = request.args.get('device_id', type=int)
    interface_id = request.args.get('interface_id', type=int)
    exclude_id = request.args.get('exclude_connection', type=int)

    if not device_id or not interface_id:
        return jsonify({'success': False, 'message': '缺少 device_id 或 interface_id'}), 400

    # 先查接口名
    iface = Interface.query.filter_by(id=interface_id, device_id=device_id).first()
    if not iface:
        return jsonify({'success': False, 'message': '接口不存在'}), 404

    # 按端口名查 ConnectionPath（含排除自身）
    query = ConnectionPath.query.filter(
        db.or_(
            db.and_(ConnectionPath.source_device_id == device_id,
                    ConnectionPath.source_port == iface.name),
            db.and_(ConnectionPath.target_device_id == device_id,
                    ConnectionPath.target_port == iface.name)
        )
    )
    if exclude_id:
        query = query.filter(ConnectionPath.id != exclude_id)

    occupied = query.count() > 0
    return jsonify({'occupied': occupied})


# ---------- API 3: 获取单个连接详情 ----------
@topology_bp.route('/api/connections/<int:connection_id>')
@login_required
@permission_required('topology:view')
def get_connection_detail(connection_id):
    """
    GET /topology/api/connections/<id>
    返回连接的完整 JSON 数据
    """
    connection = Connection.query.options(
        joinedload(Connection.source_device),
        joinedload(Connection.target_device),
        joinedload(Connection.source_interface),
        joinedload(Connection.target_interface)
    ).get(connection_id)

    if not connection:
        return jsonify({'success': False, 'message': '连接不存在'}), 404

    data = {
        'id': connection.id,
        'source_device_id': connection.source_device_id,
        'target_device_id': connection.target_device_id,
        'source_interface_id': connection.source_interface_id,
        'target_interface_id': connection.target_interface_id,
        'source_port': connection.source_port,
        'target_port': connection.target_port,
        'connection_type': connection.connection_type,
        'link_status': connection.link_status,
        'bandwidth': connection.bandwidth,
        'media_type': connection.media_type,
        'vlan_id': connection.vlan_id,
        'discovered_by': connection.discovered_by,
        'description': connection.description,
        'created_at': connection.created_at.isoformat() if connection.created_at else None,
        'updated_at': connection.updated_at.isoformat() if connection.updated_at else None,
        'discovery_time': connection.discovery_time.isoformat() if connection.discovery_time else None,
        'tx_bytes': connection.tx_bytes,
        'rx_bytes': connection.rx_bytes,
        'tx_errors': connection.tx_errors,
        'rx_errors': connection.rx_errors,
        'confidence': connection.confidence,
        # 方便前端显示的冗余字段
        'source_device_name': connection.source_device.name if connection.source_device else None,
        'target_device_name': connection.target_device.name if connection.target_device else None,
        'source_interface_name': connection.source_interface.name if connection.source_interface else None,
        'target_interface_name': connection.target_interface.name if connection.target_interface else None,
    }
    return jsonify({'success': True, **data})


@topology_bp.route('/connections/<int:connection_id>/edit', methods=['POST'])
@login_required
@permission_required('topology:edit')
def edit_connection(connection_id):
    """
    POST /topology/connections/<id>/edit
    处理编辑连接表单提交
    """
    # 验证 CSRF token（根据项目实际实现，此处假设已通过装饰器或中间件处理）
    # if not validate_csrf_token():
    #     return jsonify({'success': False, 'message': 'CSRF验证失败'}), 400

    # 获取连接对象
    connection = ConnectionPath.query.get(connection_id)
    if not connection:
        return jsonify({'success': False, 'message': '连接不存在'}), 404

    # 获取表单数据
    source_device_id = request.form.get('source_device_id', type=int)
    target_device_id = request.form.get('target_device_id', type=int)
    source_interface_id = request.form.get('source_interface_id', type=int) or None
    target_interface_id = request.form.get('target_interface_id', type=int) or None
    source_port = request.form.get('source_port', '').strip()
    target_port = request.form.get('target_port', '').strip()
    connection_type = request.form.get('connection_type')
    link_status = request.form.get('link_status')
    bandwidth = request.form.get('bandwidth', type=int) or None
    media_type = request.form.get('media_type') or None
    vlan_id = request.form.get('vlan_id') or None
    discovered_by = request.form.get('discovered_by') or None
    description = request.form.get('description') or None

    # 基本验证
    if not all([source_device_id, target_device_id, source_port, target_port, connection_type, link_status]):
        return jsonify({'success': False, 'message': '缺少必填字段'}), 400

    if source_device_id == target_device_id:
        return jsonify({'success': False, 'message': '源设备和目标设备不能相同'}), 400

    # 验证设备存在
    source_device = Device.query.get(source_device_id)
    target_device = Device.query.get(target_device_id)
    if not source_device or not target_device:
        return jsonify({'success': False, 'message': '设备不存在'}), 400

    # ---------- 处理手动输入端口：自动查找或创建接口 ----------
    if not source_interface_id and source_port:
        # 查找是否已有同名接口
        existing_iface = Interface.query.filter_by(
            device_id=source_device_id,
            name=source_port
        ).first()
        if existing_iface:
            source_interface_id = existing_iface.id
        else:
            # 创建新接口
            new_iface = Interface(
                device_id=source_device_id,
                name=source_port,
                description='由连接管理自动创建',
                # 可根据需要设置其他默认字段，如 admin_status='up', speed=0 等
            )
            db.session.add(new_iface)
            db.session.flush()  # 获取新接口的 ID
            source_interface_id = new_iface.id

    if not target_interface_id and target_port:
        existing_iface = Interface.query.filter_by(
            device_id=target_device_id,
            name=target_port
        ).first()
        if existing_iface:
            target_interface_id = existing_iface.id
        else:
            new_iface = Interface(
                device_id=target_device_id,
                name=target_port,
                description='由连接管理自动创建',
            )
            db.session.add(new_iface)
            db.session.flush()
            target_interface_id = new_iface.id

    # ---------- 验证接口存在（如果提供了接口ID） ----------
    if source_interface_id:
        iface = Interface.query.filter_by(id=source_interface_id, device_id=source_device_id).first()
        if not iface:
            return jsonify({'success': False, 'message': '源接口不存在或不属于所选设备'}), 400
    if target_interface_id:
        iface = Interface.query.filter_by(id=target_interface_id, device_id=target_device_id).first()
        if not iface:
            return jsonify({'success': False, 'message': '目标接口不存在或不属于所选设备'}), 400

    # ---------- 端口占用检查（排除自身） ----------
    if source_interface_id:
        occupied = ConnectionPath.query.filter(
            ConnectionPath.id != connection_id,
            (
                (ConnectionPath.source_device_id == source_device_id) &
                (ConnectionPath.source_interface_id == source_interface_id)
            ) | (
                (ConnectionPath.target_device_id == source_device_id) &
                (ConnectionPath.target_interface_id == source_interface_id)
            )
        ).first()
        if occupied:
            return jsonify({'success': False, 'message': '源端口已被其他连接占用'}), 400

    if target_interface_id:
        occupied = ConnectionPath.query.filter(
            ConnectionPath.id != connection_id,
            (
                (ConnectionPath.source_device_id == target_device_id) &
                (ConnectionPath.source_interface_id == target_interface_id)
            ) | (
                (ConnectionPath.target_device_id == target_device_id) &
                (ConnectionPath.target_interface_id == target_interface_id)
            )
        ).first()
        if occupied:
            return jsonify({'success': False, 'message': '目标端口已被其他连接占用'}), 400

    # ---------- 更新连接对象 ----------
    connection.source_device_id = source_device_id
    connection.target_device_id = target_device_id
    connection.source_interface_id = source_interface_id
    connection.target_interface_id = target_interface_id
    connection.source_port = source_port
    connection.target_port = target_port
    connection.connection_type = connection_type
    connection.link_status = link_status
    connection.bandwidth = bandwidth
    connection.media_type = media_type
    connection.vlan_id = vlan_id
    connection.discovered_by = discovered_by
    connection.description = description
    connection.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        log_audit('update', 'connection', connection.id, f'编辑连接关系 #{connection.id}',
                  details={'source_device_id': source_device_id, 'target_device_id': target_device_id},
                  user_id=current_user.id)
        return jsonify({'success': True, 'message': '连接更新成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'编辑连接失败: {e}')
        return jsonify({'success': False, 'message': '数据库错误'}), 500


def check_connection_status(connection):
    """检查单个连接的当前状态"""
    # 获取源设备和目标设备
    src_dev = Device.query.get(connection.source_device_id)
    tgt_dev = Device.query.get(connection.target_device_id)
    if not src_dev or not tgt_dev:
        return None

    # 使用 SNMP 获取源端口状态（如果设备支持）
    src_ip = src_dev.management_ip or src_dev.ip_address
    src_community = src_dev.snmp_community or 'public'
    # 注意：需要知道端口的 ifIndex，这里简化：通过接口名称查找 ifIndex
    src_interface = Interface.query.filter_by(device_id=src_dev.id, name=connection.source_port).first()
    if src_interface and src_interface.snmp_index:
        try:
            # 获取 ifOperStatus
            if_oper_oid = f'1.3.6.1.2.1.2.2.1.8.{src_interface.snmp_index}'
            status_val = snmp_get(src_ip, if_oper_oid, src_community)
            # 1 表示 up, 2 表示 down
            if status_val == 1:
                return 'active'
            else:
                return 'down'
        except Exception as e:
            print(f"SNMP获取端口状态失败: {e}")

    # 回退方案：ping 目标设备 IP
    tgt_ip = tgt_dev.management_ip or tgt_dev.ip_address
    if is_valid_target_ip(tgt_ip):
        import subprocess
        result = subprocess.run(['ping', '-n', '1', '-w', '1000', tgt_ip],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return 'active'
        else:
            return 'down'
    return None

@topology_bp.route('/api/connections/status', methods=['GET'])
@login_required
@permission_required('topology:view')
def api_get_connection_status():
    """获取所有连接的状态摘要"""
    connections = ConnectionPath.query.all()
    result = []
    for conn in connections:
        result.append({
            'id': conn.id,
            'source_device': conn.source_device.name if conn.source_device else None,
            'source_port': conn.source_port,
            'target_device': conn.target_device.name if conn.target_device else None,
            'target_port': conn.target_port,
            'status': conn.link_status,
            'last_seen': conn.updated_at.isoformat() if conn.updated_at else None
        })
    return jsonify({'success': True, 'connections': result})



@topology_bp.route('/api/discovery/tasks/<int:task_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
@permission_required('topology:edit')
def discovery_task_detail(task_id):
    """发现任务详情、更新、删除"""
    task = DiscoveryTask.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    
    # GET - 获取任务详情
    if request.method == 'GET':
        task_dict = task.to_dict()
        if task.discovery_mode == 'ipmac':
            task_dict['core_device_name'] = get_device_name(task.core_device_id)
            task_dict['access_device_count'] = len(task.get_access_device_ids())
        return jsonify({
            'success': True,
            'task': task_dict
        })
    
    # PUT - 更新任务
    elif request.method == 'PUT':
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': '无效的请求数据'}), 400
            
            # 更新基础字段
            if 'task_name' in data:
                task.name = data['task_name']
            if 'description' in data:
                task.description = data['description']
            if 'schedule_type' in data:
                task.schedule_type = data['schedule_type']
            if 'interval_seconds' in data:
                task.interval_seconds = data['interval_seconds']
            if 'cron_expression' in data:
                task.cron_expression = data['cron_expression']
            if 'max_depth' in data:
                task.max_depth = data['max_depth']
            if 'max_hops' in data:
                task.max_hops = data['max_hops']
            if 'max_threads' in data:
                task.max_threads = data['max_threads']
            if 'scan_timeout' in data:
                task.scan_timeout = data['scan_timeout']
            if 'rate_limit' in data:
                task.rate_limit = data['rate_limit']
            if 'auto_save' in data:
                task.auto_save = data['auto_save']
            if 'overwrite_existing' in data:
                task.overwrite_existing = data['overwrite_existing']
            if 'create_missing' in data:
                task.create_missing = data['create_missing']
            if 'enabled' in data:
                task.enabled = data['enabled']
            
            # 更新发现模式相关字段
            discovery_mode = data.get('discovery_mode', 'protocol')
            task.discovery_mode = discovery_mode
            
            if discovery_mode == 'protocol':
                # 协议发现相关字段
                if 'discovery_type' in data:
                    task.discovery_type = data['discovery_type']
                if 'target_type' in data:
                    task.target_type = data['target_type']
                if 'target_value' in data:
                    task.set_target_value(data['target_value'])
                if 'use_lldp' in data:
                    task.use_lldp = data['use_lldp']
                if 'use_cdp' in data:
                    task.use_cdp = data['use_cdp']
                if 'use_snmp' in data:
                    task.use_snmp = data['use_snmp']
                if 'use_icmp' in data:
                    task.use_icmp = data['use_icmp']
                if 'use_arp' in data:
                    task.use_arp = data['use_arp']
                # ===== 添加这一行 =====
                if 'use_snmp_mac' in data:
                    task.use_snmp_mac = data['use_snmp_mac']
                # ======================
                if 'snmp_community' in data:
                    task.snmp_community = data['snmp_community']
                if 'snmp_version' in data:
                    task.snmp_version = data['snmp_version']
                if 'snmp_timeout' in data:
                    task.snmp_timeout = data['snmp_timeout']
                if 'snmp_retries' in data:
                    task.snmp_retries = data['snmp_retries']
                
            elif discovery_mode == 'ipmac':
                # IP/MAC 发现相关字段
                if 'core_device_id' in data:
                    task.core_device_id = data['core_device_id']
                if 'access_device_ids' in data:
                    task.set_access_device_ids(data['access_device_ids'])
                if 'target_value' in data:
                    task.set_target_value(data['target_value'])
            
            # 更新时间戳
            task.updated_at = datetime.now(timezone.utc)
            
            if not task.created_by and current_user.is_authenticated:
                task.created_by = current_user.username
            
            db.session.commit()
            log_audit('update', 'discovery_task', task.id, f'更新发现任务 #{task.id}',
                      details={'task_name': task.name},
                      user_id=current_user.id)

            # ===== 根据调度类型和启用状态更新调度器任务 =====
            from scheduler import (schedule_discovery_task, schedule_discovery_task_cron,
                                   unschedule_discovery_task, get_discovery_job_info)

            # 先无条件移除旧调度，确保切换时旧任务立即停止
            unschedule_discovery_task(task.id)

            result_job = None
            if task.enabled and task.schedule_type == 'interval':
                result_job = schedule_discovery_task(task.id, task.interval_seconds or 3600)
            elif task.enabled and task.schedule_type == 'cron':
                if task.cron_expression and len(task.cron_expression.strip().split()) == 5:
                    result_job = schedule_discovery_task_cron(task.id, task.cron_expression.strip())
                else:
                    print(f"[调度] 发现任务 #{task.id} Cron 表达式无效: '{task.cron_expression}'，不注册调度")
                    # 不报错，让前端显示缺少 cron 表达式

            # 返回更新后的任务数据
            task_dict = task.to_dict()
            if task.discovery_mode == 'ipmac':
                task_dict['core_device_name'] = get_device_name(task.core_device_id)
                task_dict['access_device_count'] = len(task.get_access_device_ids())

            # 附加调度器信息
            job_info = get_discovery_job_info(task.id)
            if job_info:
                task_dict['next_run_time'] = job_info['next_run_time']
                task_dict['schedule_status'] = 'scheduled'
            elif task.schedule_type in ('interval', 'cron') and task.enabled:
                task_dict['schedule_status'] = 'not_scheduled'  # 表达式无效或注册失败
            else:
                task_dict['schedule_status'] = 'manual'

            return jsonify({
                'success': True,
                'message': '任务更新成功',
                'task': task_dict
            })
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"更新发现任务失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False, 
                'message': f'更新失败: {str(e)}'
            }), 500
    
    # DELETE - 删除任务
    elif request.method == 'DELETE':
        try:
            task_name = task.name
            db.session.delete(task)
            db.session.commit()

            # 移除对应的调度器任务
            from scheduler import unschedule_discovery_task
            unschedule_discovery_task(task_id)

            log_audit('delete', 'discovery_task', task_id, f'删除发现任务 #{task_id} ({task_name})',
                      user_id=current_user.id)

            return jsonify({
                'success': True,
                'message': '任务已删除'
            })
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"删除发现任务失败: {e}")
            return jsonify({
                'success': False, 
                'message': f'删除失败: {str(e)}'
            }), 500


# 手动合并API

# 调用位置总结
# 调用位置    说明  触发方式
# background_discovery    每次发现任务完成后自动调用        自动
# api_merge_devices       手动合并API                      用户点击按钮
# api_merge_preview       预览将要合并的设备                用户点击预览

# 这样，无论是自动发现还是手动操作，都能保证设备去重的一致性。
# ====================== 设备合并 API ======================

@topology_bp.route('/api/merge_devices', methods=['POST'])
@login_required
@permission_required('topology:edit')
def api_merge_devices():
    """手动触发设备合并"""
    try:
        from services.device_service import merge_devices_by_ip_mac
        result = merge_devices_by_ip_mac()
        log_audit('execute', 'device', 0, '手动触发设备合并',
                  details={'merged_count': result.get('merged_count', 0),
                           'total_devices': result.get('total_devices', 0)},
                  user_id=current_user.id)
        return jsonify({
            'success': True,
            'message': '设备合并完成',
            'total_devices': result.get('total_devices', 0),
            'merged_count': result.get('merged_count', 0)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'合并失败: {str(e)}'
        }), 500


@topology_bp.route('/api/merge_preview', methods=['GET'])
@login_required
@permission_required('topology:view')
def api_merge_preview():
    """
    预览将要合并的设备列表
    用于前端展示哪些设备会被合并
    """
    try:
        from services.device_service import normalize_mac
        
        # 查找重复IP
        ip_groups = {}
        mac_groups = {}
        devices = Device.query.all()
        
        for device in devices:
            ip = device.management_ip or device.ip_address
            if ip:
                if ip not in ip_groups:
                    ip_groups[ip] = []
                ip_groups[ip].append({
                    'id': device.id,
                    'name': device.name,
                    'mac': device.mac_address,
                    'ip': ip,
                    'type': device.device_type,
                    'status': device.status
                })
            
            mac_norm = normalize_mac(device.mac_address or '')
            if mac_norm:
                if mac_norm not in mac_groups:
                    mac_groups[mac_norm] = []
                mac_groups[mac_norm].append({
                    'id': device.id,
                    'name': device.name,
                    'mac': device.mac_address,
                    'ip': device.management_ip or device.ip_address,
                    'type': device.device_type,
                    'status': device.status
                })
        
        # 找出需要合并的组
        duplicate_groups = []
        for ip, group in ip_groups.items():
            if len(group) > 1:
                duplicate_groups.append({
                    'type': 'ip',
                    'key': ip,
                    'devices': group
                })
        
        for mac, group in mac_groups.items():
            if len(group) > 1:
                # 检查是否已经作为IP组被包含（避免重复显示）
                # 简单处理：MAC组和IP组都显示
                duplicate_groups.append({
                    'type': 'mac',
                    'key': mac,
                    'devices': group
                })
        
        return jsonify({
            'success': True,
            'duplicate_groups': duplicate_groups,
            'total_duplicates': len(duplicate_groups)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'预览失败: {str(e)}'
        }), 500



# ====================== 导出布线表 API ======================

@topology_bp.route('/connections/export', methods=['GET'])
@login_required
@permission_required('topology:view')
def export_connections():
    """导出连接关系（CSV格式），支持当前筛选条件"""
    import csv
    import io
    from flask import make_response
    from urllib.parse import quote
    
    device_id = request.args.get('device_id', type=int)
    connection_type = request.args.get('type', 'all')
    status = request.args.get('status', 'all')
    sort_by = request.args.get('sort_by', 'created_at')
    order = request.args.get('order', 'desc')
    
    query = ConnectionPath.query
    
    if device_id:
        query = query.filter(
            or_(
                ConnectionPath.source_device_id == device_id,
                ConnectionPath.target_device_id == device_id
            )
        )
    if connection_type != 'all':
        query = query.filter(ConnectionPath.connection_type == connection_type)
    if status != 'all':
        query = query.filter(ConnectionPath.link_status == status)
    
    if sort_by == 'created_at':
        query = query.order_by(
            ConnectionPath.created_at.desc() if order == 'desc' else ConnectionPath.created_at.asc()
        )
    elif sort_by == 'source_device':
        query = query.order_by(
            ConnectionPath.source_device_id.desc() if order == 'desc' else ConnectionPath.source_device_id.asc()
        )
    elif sort_by == 'target_device':
        query = query.order_by(
            ConnectionPath.target_device_id.desc() if order == 'desc' else ConnectionPath.target_device_id.asc()
        )
    
    connections = query.all()
    
    # 准备导出数据
    export_data = []
    for conn in connections:
        export_data.append({
            'ID': conn.id,
            '源设备': conn.source_device.name if conn.source_device else 'N/A',
            '源设备ID': conn.source_device_id,
            '源端口': conn.source_port,
            '目标设备': conn.target_device.name if conn.target_device else 'N/A',
            '目标设备ID': conn.target_device_id,
            '目标端口': conn.target_port,
            '连接类型': conn.connection_type,
            '状态': conn.link_status,
            '带宽(bps)': conn.bandwidth if conn.bandwidth else '',
            '介质': conn.media_type if conn.media_type else '',
            'VLAN': conn.vlan_id if conn.vlan_id else '',
            '发现方式': conn.discovered_by if conn.discovered_by else '',
            '创建时间': conn.created_at.strftime('%Y-%m-%d %H:%M:%S') if conn.created_at else '',
            '更新时间': conn.updated_at.strftime('%Y-%m-%d %H:%M:%S') if conn.updated_at else '',
        })
    
    # 生成CSV
    output = io.StringIO()
    if export_data:
        fieldnames = export_data[0].keys()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(export_data)
    else:
        output.write("无数据")
    
    filename = f'connections_export_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    encoded_filename = quote(filename)
    
    response = make_response(output.getvalue().encode('utf-8-sig'))
    response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
    return response


@topology_bp.route('/connections/export_wiring_table', methods=['GET'])
@login_required
@permission_required('topology:view')
def export_wiring_table():
    """导出连接关系为布线表格式（CSV），与提供的布线表模板一致"""
    import csv
    import io
    from flask import make_response
    from urllib.parse import quote
    
    device_id = request.args.get('device_id', type=int)
    connection_type = request.args.get('type', 'all')
    status = request.args.get('status', 'all')
    
    query = ConnectionPath.query
    
    if device_id:
        query = query.filter(
            or_(
                ConnectionPath.source_device_id == device_id,
                ConnectionPath.target_device_id == device_id
            )
        )
    if connection_type != 'all':
        query = query.filter(ConnectionPath.connection_type == connection_type)
    if status != 'all':
        query = query.filter(ConnectionPath.link_status == status)
    
    connections = query.all()
    
    headers = [
        '序号', '本端设备', '本端机房', '本端机柜', '本端设备位', '本端设备型号', 
        '主备关系', '本端接口名称', '本端设备上架情况',
        '对端设备', '对端机房', '对端机柜', '对端设备位', '对端设备型号', 
        '主备关系', '对端端口号', '本端标签', '对端标签', '长度', '线缆类型', '颜色'
    ]
    
    export_rows = []
    row_num = 1
    
    for conn in connections:
        src_dev = conn.source_device
        tgt_dev = conn.target_device
        
        # 获取机房名称（通过 location 关系）
        src_location = src_dev.location.name if src_dev and src_dev.location else ''
        tgt_location = tgt_dev.location.name if tgt_dev and tgt_dev.location else ''
        
        # 获取机柜名称
        src_cabinet = src_dev.cabinet.name if src_dev and src_dev.cabinet else ''
        tgt_cabinet = tgt_dev.cabinet.name if tgt_dev and tgt_dev.cabinet else ''
        
        # 设备位（U位）
        src_u_position = getattr(src_dev, 'position_u', '') or ''
        tgt_u_position = getattr(tgt_dev, 'position_u', '') or ''
        
        # 设备型号
        src_model = getattr(src_dev, 'model', '') or src_dev.device_type or ''
        tgt_model = getattr(tgt_dev, 'model', '') or tgt_dev.device_type or ''
        
        # 主备关系
        src_role = getattr(src_dev, 'role', '') or 'A'
        tgt_role = getattr(tgt_dev, 'role', '') or 'A'
        
        # 设备上架情况
        src_mounted = '已上架' if src_dev and src_dev.cabinet else '未上架'
        tgt_mounted = '已上架' if tgt_dev and tgt_dev.cabinet else '未上架'
        
        # 生成标签
        src_label = f"F:{src_cabinet}-{src_u_position}_{src_model}_{conn.source_port}_{src_role}" if src_cabinet else conn.source_port
        tgt_label = f"F:{tgt_cabinet}-{tgt_u_position}_{tgt_model}_{conn.target_port}_{tgt_role}" if tgt_cabinet else conn.target_port
        
        # 线缆类型
        cable_type_map = {'copper': '铜缆', 'fiber': '光纤', 'wireless': '无线'}
        cable_type = cable_type_map.get(conn.media_type, conn.media_type or '')
        
        # 颜色
        color_map = {'active': '绿色', 'down': '红色', 'degraded': '黄色'}
        color = color_map.get(conn.link_status, '')
        
        row = [
            row_num,
            src_dev.name if src_dev else '',
            src_location,  # 现在会从 location 关系获取
            src_cabinet,
            src_u_position,
            src_model,
            src_role,
            conn.source_port,
            src_mounted,
            tgt_dev.name if tgt_dev else '',
            tgt_location,  # 现在会从 location 关系获取
            tgt_cabinet,
            tgt_u_position,
            tgt_model,
            tgt_role,
            conn.target_port,
            src_label,
            tgt_label,
            '',
            cable_type,
            color
        ]
        export_rows.append(row)
        row_num += 1
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['网络布线表'])
    writer.writerow([])
    writer.writerow(headers)
    
    for row in export_rows:
        writer.writerow(row)
    
    filename = f'布线表_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    encoded_filename = quote(filename)
    
    response = make_response(output.getvalue().encode('utf-8-sig'))
    response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
    return response
