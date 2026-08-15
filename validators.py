# app/utils/validators.py

import re
from ipaddress import ip_address, IPv4Address, IPv6Address

def validate_ip(ip_str):
    """验证IP地址格式"""
    try:
        ip = ip_address(ip_str)
        return isinstance(ip, (IPv4Address, IPv6Address))
    except ValueError:
        return False

def validate_mac(mac_str):
    """验证MAC地址格式"""
    # 支持:和-分隔符
    mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
    return bool(mac_pattern.match(mac_str))

def validate_device_name(name):
    """验证设备名称格式"""
    # 设备名称不能为空，长度在2-128字符之间
    if not name or len(name) < 2 or len(name) > 128:
        return False
    
    # 可以添加更多的验证规则
    # 例如：不允许特殊字符等
    # 这里我们只检查基本的字符集
    allowed_chars = re.compile(r'^[a-zA-Z0-9_\-\s\u4e00-\u9fa5]+$')
    return bool(allowed_chars.match(name))