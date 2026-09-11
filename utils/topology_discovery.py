# services/topology_discovery.py
"""拓扑发现公共能力：SNMP 检测、设备索引、子网扩展、协议优先级。

目标：把 blueprints/topology.py 中重复/内联的实现收敛到服务层，
便于后续继续拆分 LLDP/CDP/FDB 发现模块。
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 协议优先级，数值越高越可信。
# 用于冲突时“谁覆盖谁”，也用于保存阶段判断是否更新旧链路。
PROTOCOL_PRIORITY: Dict[str, int] = {
    'lldp': 100,
    'cdp': 90,
    'snmp_mac': 70,
    'ipmac': 60,
    'ipmac_no_ip': 50,
    'manual': 80,
    'unknown': 0,
}


def normalize_mac(mac) -> str:
    """标准化 MAC 为连续小写十六进制，如 001122334455。"""
    if not mac:
        return ''
    return ''.join(c for c in str(mac).lower() if c in '0123456789abcdef')


def is_snmp_available(ip, community='public', timeout=3, version='2c') -> bool:
    """用真实 SNMP GET 判断设备是否可管理，不依赖 UDP connect / 外部 snmpget。"""
    try:
        from utils.snmp_utils import snmp_get
        val = snmp_get(str(ip), community, version, '1.3.6.1.2.1.1.1.0', timeout=timeout)
        return val is not None
    except Exception:
        return False


def _clean_name(name) -> str:
    if not name:
        return ''
    return ''.join(c for c in str(name) if c.isalnum() or c in '-_.' or '\u4e00' <= c <= '\u9fff').strip()


class DeviceIndex:
    """把 Device 表一次性加载到内存，提供按 IP/MAC/名称的快速匹配。

    避免在发现循环里反复 Device.query.all() 或逐条模糊查询。
    """

    def __init__(self):
        self.devices: list = []
        self.by_id: Dict[int, object] = {}
        self.by_ip: Dict[str, object] = {}
        self.by_mac: Dict[str, object] = {}
        self.by_name: Dict[str, object] = {}

    def load(self):
        from models.models import Device

        self.devices = Device.query.all()
        self.by_ip.clear()
        self.by_mac.clear()
        self.by_name.clear()
        self.by_id.clear()

        for dev in self.devices:
            self.by_id.setdefault(dev.id, dev)
            for ip in (dev.management_ip, dev.ip_address):
                if ip:
                    self.by_ip.setdefault(str(ip).strip(), dev)
            mac = normalize_mac(dev.mac_address or '')
            if mac:
                self.by_mac.setdefault(mac, dev)
            if dev.name:
                self.by_name.setdefault(dev.name.strip().lower(), dev)

    def by_ip_get(self, ip):
        if not ip:
            return None
        return self.by_ip.get(str(ip).strip())

    def by_id_get(self, dev_id):
        if dev_id is None:
            return None
        return self.by_id.get(int(dev_id))

    def by_mac_get(self, mac):
        if not mac:
            return None
        return self.by_mac.get(normalize_mac(mac))

    def by_name_exact(self, name):
        if not name:
            return None
        return self.by_name.get(str(name).strip().lower())

    def by_name_fuzzy(self, name):
        """先精确、再等值、再包含，返回第一个命中，避免每轮查库。"""
        if not name:
            return None
        dev = self.by_name_exact(name)
        if dev:
            return dev
        clean = _clean_name(name)
        if not clean or len(clean) < 2:
            return None
        # 等值
        for d in self.devices:
            if _clean_name(d.name or '') == clean:
                return d
        # 包含
        for d in self.devices:
            if clean in _clean_name(d.name or ''):
                return d
        return None


def expand_subnet_targets(subnet_str: str, max_hosts: int = 4096) -> List[str]:
    """展开子网种子。

    - 小网段（/24 及以下常见规模）尽量全扫。
    - 大网段按 max_hosts 上限均匀采样，避免一次任务把网络打满。
    """
    import ipaddress

    network = ipaddress.ip_network(str(subnet_str).strip(), strict=False)
    if network.version != 4:
        return []
    hosts = list(network.hosts())
    if not hosts:
        return []
    if len(hosts) <= max_hosts:
        return [str(ip) for ip in hosts]
    step = max(1, len(hosts) // max_hosts)
    sampled = [str(hosts[i]) for i in range(0, len(hosts), step)][:max_hosts]
    last_ip = str(hosts[-1])
    if last_ip not in sampled:
        sampled.append(last_ip)
    return sampled
