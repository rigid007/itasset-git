"""
device_config.py - 设备配置获取工具
通过 SSH (paramiko) 从网络设备获取 running-config / startup-config 等配置

对华为/H3C 使用原始 paramiko（避免 netmiko 自动发送不兼容命令），
对 Cisco/Juniper/锐捷等使用 netmiko（稳定可靠）。
"""
import logging
import re
import socket
import time
from datetime import datetime
from typing import Dict, Tuple, Optional

import paramiko
from utils.network_utils import ping_device

logger = logging.getLogger(__name__)

# ==================== 品牌 -> 厂商族 ====================
# 用于判断设备的命令族（不用于 netmiko device_type）

_VENDOR_FAMILY = {}


def _init_vendor_family():
    """品牌名 → 厂商族 (huawei / cisco / juniper / ruijie / arista / linux / generic)"""
    # 注意: 更具体的匹配放在前面
    _VENDOR_FAMILY['procurve'] = 'procurve'
    _VENDOR_FAMILY['hp procurve'] = 'procurve'
    _VENDOR_FAMILY['hp_procurve'] = 'procurve'

    huawei_brands = {
        'huawei', '华为', 'h3c', '华三', 'comware',
        'hp', 'hp comware', 'hp_comware', 'hpe',
    }
    cisco_brands = {'cisco', '思科'}
    juniper_brands = {'juniper'}
    ruijie_brands = {'ruijie', '锐捷', 'rgos'}
    arista_brands = {'arista'}
    linux_brands = {'linux'}

    for b in huawei_brands:
        _VENDOR_FAMILY[b] = 'huawei'
    for b in cisco_brands:
        _VENDOR_FAMILY[b] = 'cisco'
    for b in juniper_brands:
        _VENDOR_FAMILY[b] = 'juniper'
    for b in ruijie_brands:
        _VENDOR_FAMILY[b] = 'ruijie'
    for b in arista_brands:
        _VENDOR_FAMILY[b] = 'arista'
    for b in linux_brands:
        _VENDOR_FAMILY[b] = 'linux'


_init_vendor_family()

# ==================== 设备类型 -> 配置命令映射 ====================

CONFIG_COMMANDS = {
    'huawei': {
        'running':   'display current-configuration',
        'startup':   'display saved-configuration',
        'vlan':      'display vlan',
        'interface': 'display interface brief',
        'version':   'display version',
    },
    'cisco': {
        'running':   'show running-config',
        'startup':   'show startup-config',
        'vlan':      'show vlan brief',
        'interface': 'show interfaces',
        'version':   'show version',
    },
    'juniper': {
        'running':   'show configuration | display set',
        'startup':   'show configuration | display set',
        'vlan':      'show vlans',
        'interface': 'show interfaces terse',
        'version':   'show version',
    },
    'ruijie': {
        'running':   'show running-config',
        'startup':   'show startup-config',
        'vlan':      'show vlan brief',
        'interface': 'show interfaces',
        'version':   'show version',
    },
    'arista': {
        'running':   'show running-config',
        'startup':   'show startup-config',
        'vlan':      'show vlan brief',
        'interface': 'show interfaces',
        'version':   'show version',
    },
    'procurve': {
        'running':   'show running-config',
        'startup':   'show config',
        'vlan':      'show vlan',
        'interface': 'show interfaces brief',
        'version':   'show version',
    },
    'linux': {
        'running':   'cat /etc/network/interfaces 2>/dev/null || cat /etc/netplan/*.yaml 2>/dev/null || ip addr show',
        'startup':   'cat /etc/network/interfaces 2>/dev/null || cat /etc/netplan/*.yaml 2>/dev/null || echo "startup config not applicable"',
        'vlan':      'ip link show type vlan 2>/dev/null || echo "no vlans"',
        'interface': 'ip addr show',
        'version':   'uname -a',
    },
    'generic': {
        'running':   'show running-config',
        'startup':   'show startup-config',
        'vlan':      'show vlan brief',
        'interface': 'show interfaces',
        'version':   'show version',
    },
}

# ==================== 厂商 -> netmiko device_type ====================
# 仅用于 Cisco/Juniper/Arista/ProCurve（这些 netmiko 驱动稳定）

VENDOR_TO_NETMIKO = {
    'cisco':    'cisco_ios',
    'juniper':  'juniper',
    'arista':   'arista_eos',
    'ruijie':   'ruijie_os',
    'procurve': 'hp_procurve',
}

# Huawei/H3C 不走 netmiko，用下面 paramiko 直接连接

# ==================== 错误消息映射 ====================

ERROR_MESSAGES = {
    'AuthenticationException':    'SSH 认证失败，请检查用户名/密码是否正确',
    'NetmikoTimeoutException':    'SSH 连接超时，设备不可达或 SSH 端口未开放',
    'NetmikoAuthenticationException': 'SSH 认证被拒绝，请检查凭据',
    'ConnectionRefusedError':     'SSH 连接被拒绝，请检查设备 SSH 服务是否开启',
    'TimeoutError':               '连接超时，设备响应过慢',
    'OSError':                    '网络错误，设备不可达',
    'EOFError':                   '设备主动断开连接（可能被 ACL 限制）',
    'socket.timeout':             'Socket 连接超时',
    'socket.gaierror':            '无法解析设备 IP 地址',
    'ValueError':                 '设备参数错误',
    'SSHException':               'SSH 协议错误，可能密钥交换失败',
}


def resolve_device_credential(device) -> Tuple[Optional[str], Optional[str], int]:
    """
    解析设备的 SSH 凭据
    优先级: device.credential (统一凭据) > device 上的直接字段
    返回: (username, password, port)
    """
    from models.config_models import Credential

    username = None
    password = None
    port = 22

    if device.credential_id and device.credential:
        cred = device.credential
        if cred.enabled:
            username = cred.username
            password = cred.get_password()
            port = cred.port or 22

    if not username and device.ssh_username:
        username = device.ssh_username
        password = device.ssh_password

    if not username:
        return None, None, port

    return username, password, port


def resolve_vendor_family(device) -> str:
    """
    根据 brand 和 device_type 判断设备的厂商族
    返回: 'huawei' | 'cisco' | 'juniper' | 'ruijie' | 'arista' | 'procurve' | 'linux' | 'generic'
    """
    brand = (device.brand or '').strip().lower()
    dt = (device.device_type or '').strip().lower()

    # 1. 品牌精确匹配（按 key 长度降序，优先匹配更具体的品牌名）
    if brand:
        for key in sorted(_VENDOR_FAMILY.keys(), key=len, reverse=True):
            if key in brand:
                return _VENDOR_FAMILY[key]

    # 2. device_type 推断
    if dt in ('huawei', 'huawei_vrp', 'h3c', 'hp_comware'):
        return 'huawei'
    if dt in ('cisco_ios', 'cisco_ios_xe', 'cisco_xe', 'cisco_nxos', 'cisco_asa', 'cisco_xr'):
        return 'cisco'
    if dt in ('juniper', 'juniper_junos'):
        return 'juniper'
    if dt in ('ruijie', 'rgos'):
        return 'ruijie'
    if dt in ('arista', 'arista_eos'):
        return 'arista'
    if dt in ('hp_procurve',):
        return 'procurve'
    if dt in ('linux', 'server'):
        return 'linux'
    if dt in ('firewall',):
        return 'cisco'

    # 3. 无法判断 → generic（发送 cisco 风格命令，大多数设备能处理）
    return 'generic'


def get_device_command(device, config_type: str) -> str:
    """获取设备支持的特定配置命令"""
    vendor = resolve_vendor_family(device)
    commands = CONFIG_COMMANDS.get(vendor, CONFIG_COMMANDS['generic'])
    return commands.get(config_type, '')


def get_supported_config_types(device) -> list:
    """返回设备支持的所有配置类型"""
    vendor = resolve_vendor_family(device)
    commands = CONFIG_COMMANDS.get(vendor, CONFIG_COMMANDS['generic'])
    return list(commands.keys())


def capture_device_config(device, config_type: str = 'running', timeout: int = 30) -> Dict:
    """
    通过 SSH 从设备获取配置内容

    参数:
        device: Device ORM 对象
        config_type: 'running' / 'startup' / 'vlan' / 'interface' / 'version'
        timeout: SSH 连接+命令执行超时 (秒)

    返回:
        {'success': bool, 'content': str, 'line_count': int, 'command': str,
         'device_ip': str, 'error': str}
    """
    result = {
        'success': False,
        'content': '',
        'line_count': 0,
        'command': '',
        'device_ip': '',
        'error': '',
    }

    # 1. 检查管理IP
    ip = device.management_ip or device.ip_address
    if not ip:
        result['error'] = '设备未配置管理 IP'
        return result
    result['device_ip'] = ip

    # 2. 解析凭据
    username, password, ssh_port = resolve_device_credential(device)
    if not username:
        result['error'] = '设备未配置 SSH 凭据 (ssh_username/credential_id)'
        return result

    # 3. 获取命令
    command = get_device_command(device, config_type)
    if not command:
        result['error'] = f'设备不支持 "{config_type}" 配置获取'
        return result
    result['command'] = command

    # 4. Ping 在线检测
    try:
        online, latency = ping_device(ip, timeout=3)
        if not online:
            result['error'] = f'设备 {ip} 不可达 (ping 失败)'
            return result
    except Exception as e:
        logger.warning(f"Ping {ip} 异常: {e}，继续尝试 SSH")

    # 5. 判断厂商
    vendor = resolve_vendor_family(device)
    brand = (device.brand or '')
    dt = (device.device_type or '')
    logger.info(f"SSH {username}@{ip}:{ssh_port}, vendor={vendor}, "
                f"brand={brand!r}, device_type={dt!r}, command={command}")
    print(f"\n[CONFIG-CAPTURE] brand={brand!r}  device_type={dt!r}")
    print(f"[CONFIG-CAPTURE] vendor_family={vendor}  command={command}")

    # 6. 执行 SSH 获取
    try:
        if vendor in ('huawei',):
            # Huawei/H3C/Comware → 原始 paramiko invoke_shell
            content = _paramiko_get_config(ip, username, password, ssh_port,
                                           command, is_huawei_comware=True, timeout=timeout)
        elif vendor in VENDOR_TO_NETMIKO:
            # Cisco/Juniper/Arista/Ruijie/ProCurve → netmiko
            netmiko_type = VENDOR_TO_NETMIKO[vendor]
            content = _netmiko_get_config(ip, username, password, ssh_port,
                                          netmiko_type, command, timeout)
        else:
            # generic/linux → 智能检测: 通过 SSH banner 自动识别设备类型
            content, detected_type = _smart_paramiko_get_config(
                ip, username, password, ssh_port, command, config_type, timeout)
            if detected_type:
                print(f"[CONFIG-CAPTURE] banner 自动识别: {detected_type}")
                # 如果是华为/H3C，用识别到的命令重新设一次（仅用于记录）
                if detected_type == 'huawei':
                    result['command'] = CONFIG_COMMANDS['huawei'].get(config_type, command)

        if content:
            result['success'] = True
            result['content'] = content.strip()
            result['line_count'] = len(content.splitlines())
            logger.info(f"SSH {ip} 获取成功, {result['line_count']} 行")
        else:
            result['error'] = f'命令 "{command}" 返回空内容'

    except paramiko.AuthenticationException:
        result['error'] = 'SSH 认证失败，请检查用户名/密码'
        logger.warning(f"SSH 认证失败 {ip}")
    except Exception as e:
        cls_name = type(e).__name__
        result['error'] = ERROR_MESSAGES.get(cls_name, f'连接失败: {str(e)}')
        logger.error(f"SSH {ip} 失败: {cls_name}: {e}", exc_info=True)

    return result


# ==================== Smart paramiko（generic 时自动检测厂商） ====================

def _detect_vendor_from_banner(banner: str) -> Optional[str]:
    """从 SSH banner 中检测设备厂商"""
    lower = banner.lower()
    huawei_kw = (
        'comware', 'h3c', 'vrp', 'quidway', 'huawei',
        's5700', 's3700', 's2700', 's7700', 's9700',
        's12700', 's9300', 'ce6800', 'ce12800',
        'ls52t', 'ls5m', 'ls53', 'ls55', 'ls57', 'ls58',
    )
    for kw in huawei_kw:
        if kw in lower:
            return 'huawei'
    cisco_kw = ('cisco ios', 'cisco nx-os', 'cisco ios-xe', 'cisco xr')
    for kw in cisco_kw:
        if kw in lower:
            return 'cisco'
    return None


def _send_preprocess(channel, is_huawei_comware: bool):
    """发送分页禁用预处理 — H3C 和华为发送不同命令，确保兼容"""
    if is_huawei_comware:
        # 华为 VRP5/VRP8 用 screen-length 0 temporary
        channel.send("screen-length 0 temporary\n")
        time.sleep(0.3)
        # H3C Comware 用 screen-length disable，两个都发确保有一效
        channel.send("screen-length disable\n")
        time.sleep(0.3)
        channel.send("undo terminal monitor\n")
        time.sleep(0.3)
        channel.send("idle-timeout 0\n")
        time.sleep(0.3)


def _smart_paramiko_get_config(host: str, username: str, password: str, port: int,
                                command: str, config_type: str = 'running',
                                timeout: int = 60) -> Tuple[str, Optional[str]]:
    """
    智能连接：尝试多种命令组合，直到成功获取配置。

    对于品牌未知的设备：
    1. 先尝试给定命令
    2. 如果输出包含错误标志 (Unrecognized, Incomplete, Error 等)，切换厂商重试

    返回: (content, detected_vendor_or_None)
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    client.connect(
        hostname=host, port=port, username=username, password=password,
        timeout=30, auth_timeout=30, banner_timeout=15,
        look_for_keys=False, allow_agent=False, compress=True,
    )

    try:
        channel = client.invoke_shell(width=500, height=2000)
        channel.settimeout(30)

        # 读取 banner
        time.sleep(2)
        _drain_channel(channel)

        # 从 banner 自动识别厂商
        banner_data = b''
        while channel.recv_ready():
            banner_data += channel.recv(65535)
        banner = banner_data.decode('utf-8', errors='ignore')
        detected = _detect_vendor_from_banner(banner)

        # --- 构建待尝试的命令列表 ---
        # [(command, is_huawei_comware), ...]
        candidates = []

        if detected == 'huawei':
            # 已知是华为/H3C：直接发预处理 + display current-configuration
            hw_cmd = CONFIG_COMMANDS['huawei'].get(config_type, command)
            candidates.append((hw_cmd, True))
        elif detected == 'cisco':
            candidates.append((command, False))
        else:
            # 未知厂商：先试给定命令，再试华为命令
            candidates.append((command, False))
            hw_cmd = CONFIG_COMMANDS['huawei'].get(config_type, '')
            if hw_cmd and hw_cmd != command:
                candidates.append((hw_cmd, True))

        # --- 逐个尝试 ---
        content = ""
        final_detected = detected
        for idx, (cmd, is_hw) in enumerate(candidates):
            if idx > 0:
                # 上一个命令失败了，打印信息
                logger.info(f"Smart retry with command: {cmd}")

            print(f"[SMART] try #{idx+1}: cmd=\"{cmd}\" is_hw={is_hw}")

            # 只有第一次尝试或切换厂商时才发预处理
            if idx == 0 or (idx > 0 and is_hw):
                if is_hw:
                    _send_preprocess(channel, is_huawei_comware=True)

            _drain_channel(channel)

            # 发送命令
            channel.send(cmd + "\n")
            output = _read_until_prompt(channel, timeout)
            cleaned = _clean_output(output, cmd)

            if _is_valid_output(cleaned):
                content = cleaned
                final_detected = detected or ('huawei' if is_hw else None)
                break
            else:
                logger.warning(f"Command \"{cmd}\" returned invalid output, retrying...")

        return content, final_detected

    finally:
        try:
            channel.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass


def _is_valid_output(output: str) -> bool:
    """
    判断命令输出是否有效（不是错误信息）。
    华为/H3C/思科设备命令错误时输出较短包含特定关键词。
    配置内容的输出应该有足够长度和合理结构。
    """
    if not output or len(output.strip()) < 50:
        return False
    lower = output.lower()
    error_keywords = [
        'unrecognized command', 'incomplete command',
        'ambiguous command', 'too many parameters',
        'error:', '% invalid', 'syntax error',
    ]
    for kw in error_keywords:
        if kw in lower:
            return False
    # 对 display current-configuration：输出应该包含许多 "version" / "sysname" / "vlan" / "#" 等
    # 如果输出很短(1000行以内也需要保证有足够内容)但包含错误关键字则拒绝
    return True


# ==================== paramiko 直连（华为/H3C/Linux/Generic） ====================

def _paramiko_get_config(host: str, username: str, password: str, port: int,
                          command: str, is_huawei_comware: bool = False,
                          timeout: int = 60) -> str:
    """
    使用原始 paramiko invoke_shell 连接设备并执行命令。
    参考 e:\back 中已验证成功的实现。

    返回命令输出文本，失败抛异常。
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    client.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        timeout=30,
        auth_timeout=30,
        banner_timeout=15,
        look_for_keys=False,
        allow_agent=False,
        compress=True,
    )

    try:
        channel = client.invoke_shell(width=500, height=2000)
        channel.settimeout(30)

        # 等待初始提示符，读取 banner
        time.sleep(2)
        banner_data = b''
        while channel.recv_ready():
            banner_data += channel.recv(65535)
        banner = banner_data.decode('utf-8', errors='ignore').lower()

        # 从 SSH banner 自动检测厂商（覆盖数据库中的空 brand）
        if not is_huawei_comware:
            if any(kw in banner for kw in (
                'comware', 'h3c', 'vrp', 'quidway', 'huawei',
                's5700', 's3700', 's2700', 's7700', 's9700',
                's12700', 's9300', 'ce6800', 'ce12800',
                'ls52t', 'ls5m', 'ls53', 'ls55', 'ls57', 'ls58',
            )):
                is_huawei_comware = True
                print(f"[CONFIG-CAPTURE] 自动检测: banner 包含华为/H3C 特征，启用 Comware 模式")
                logger.info(f"自动检测 Huawei/Comware: banner 关键字匹配")

        # 发送分页禁用等预处理命令
        if is_huawei_comware:
            _send_preprocess(channel, is_huawei_comware=True)
        else:
            # 其他设备（linux 等）不需要预处理
            pass

        _drain_channel(channel)

        # 发送主命令
        channel.send(command + "\n")

        # 读取输出，直到检测到命令提示符
        output = _read_until_prompt(channel, timeout)
        return _clean_output(output, command)

    finally:
        try:
            channel.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass


def _drain_channel(channel):
    """清空 channel 缓冲区的残留数据"""
    try:
        while channel.recv_ready():
            channel.recv(65535)
    except Exception:
        pass


def _read_until_prompt(channel, max_wait: int = 120) -> str:
    """
    循环读取 channel 输出，直到检测到设备提示符（>、#、]）

    - 自动处理 ---- More ---- 分页提示（发送空格翻页）
    - 超时 120 秒（大型配置需要较长时间）
    """
    output = ""
    waited = 0
    while waited < max_wait:
        time.sleep(0.5)
        waited += 0.5
        if channel.recv_ready():
            data = channel.recv(65535).decode('utf-8', errors='ignore')
            output += data

            # 处理分页提示：发送空格翻页
            if '---- More ----' in output or '--More--' in output:
                channel.send(" ")
                time.sleep(0.5)
                continue

            # 检测是否出现了命令提示符
            stripped = output.strip()
            if stripped and (stripped.endswith('>') or stripped.endswith('#')
                             or stripped.endswith(']')):
                # 确认是提示符而不是配置内容中的巧合字符：
                # 提示符通常在单独一行，格式为 <hostname> 或 [hostname] 或 hostname#
                last_line = stripped.split('\n')[-1].strip()
                if re.match(r'^<[\w._-]+>$', last_line):
                    break
                if re.match(r'^\[[\w._-]+\]$', last_line):
                    break
                if re.match(r'^[\w._-]+#$', last_line):
                    break
                # 不是提示符就继续读
                continue
    return output


def _clean_output(raw: str, command: str) -> str:
    """
    清理 SSH 输出（与 e:\back 备份项目使用相同算法）：
    - 移除 ANSI 转义序列和控制字符
    - 移除分页命令回显和预处理命令回显
    - 移除命令提示符行和分页提示
    """
    if not raw:
        return ""

    # 移除 ANSI 转义序列
    raw = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw)
    # 移除控制字符
    raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
    # 移除特殊符号
    raw = re.sub(r'[⨪⨀⨁⨂⨃⨄⨅⨆★☆◆◇○●]', '', raw)
    # 移除登录/版权信息
    raw = re.sub(r'Press ANY KEY to get started.*?\n', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'Copyright.*?All rights reserved.*?\n', '', raw, flags=re.IGNORECASE)

    lines = raw.split('\n')
    cleaned = []
    skip_keywords = [
        'Username:', 'Password:', 'Login:',
        'decompiling', 'reverse-engineering',
        'screen-length', 'undo terminal monitor', 'idle-timeout',
        '--More--', '---- More ----',
    ]

    for line in lines:
        stripped = line.strip()

        # 跳过无关行
        should_skip = False
        for kw in skip_keywords:
            if kw.lower() in stripped.lower():
                should_skip = True
                break
        if should_skip:
            continue

        # 跳过命令回显行
        if command and stripped == command:
            continue

        # 跳过提示符行: <Hostname>, [Hostname], Hostname#, Hostname>, Hostname$
        if re.match(r'^<[\w._-]+>\s*$', stripped):
            continue
        if re.match(r'^\[[\w._-]+\]\s*$', stripped):
            continue
        if re.match(r'^[\w._-]+[#>$]\s*$', stripped):
            continue

        cleaned.append(line)

    return '\n'.join(cleaned).strip()


# ==================== netmiko 连接（Cisco/Juniper/Arista/锐捷/ProCurve） ====================

def _netmiko_get_config(host: str, username: str, password: str, port: int,
                         netmiko_type: str, command: str, timeout: int = 30) -> str:
    """
    使用 netmiko 连接设备并执行命令。
    适用于 Cisco/Juniper/Arista/Ruijie/ProCurve（驱动成熟，自动处理分页）。
    """
    from netmiko import ConnectHandler

    device_params = {
        'device_type': netmiko_type,
        'host': host,
        'username': username,
        'password': password,
        'port': port,
        'timeout': timeout,
        'conn_timeout': timeout,
        'auth_timeout': timeout,
        'banner_timeout': 15,
        'global_cmd_verify': False,
    }

    with ConnectHandler(**device_params) as conn:
        output = conn.send_command_timing(
            command,
            read_timeout=timeout,
        )
        # netmiko 自动 disconnect
        return output


# ==================== SSH 连通性测试 ====================

def test_device_connectivity(device) -> Dict:
    """快速测试设备 SSH 连通性"""
    ip = device.management_ip or device.ip_address
    if not ip:
        return {'reachable': False, 'ssh_ok': False, 'error': '无管理IP', 'latency_ms': 0}

    try:
        online, latency = ping_device(ip, timeout=3)
    except Exception:
        online, latency = False, 0

    if not online:
        return {'reachable': False, 'ssh_ok': False, 'error': 'Ping不通', 'latency_ms': 0}

    username, password, ssh_port = resolve_device_credential(device)
    if not username:
        return {'reachable': True, 'ssh_ok': False, 'error': '无SSH凭据', 'latency_ms': latency}

    # 简单 SSH 连接测试
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ip, port=ssh_port, username=username, password=password,
            timeout=10, auth_timeout=10, banner_timeout=10,
            look_for_keys=False, allow_agent=False,
        )
        client.close()
        return {'reachable': True, 'ssh_ok': True, 'error': '', 'latency_ms': latency}
    except paramiko.AuthenticationException:
        return {'reachable': True, 'ssh_ok': False, 'error': 'SSH认证失败', 'latency_ms': latency}
    except Exception as e:
        return {'reachable': True, 'ssh_ok': False,
                'error': f'SSH测试异常: {type(e).__name__}', 'latency_ms': latency}
