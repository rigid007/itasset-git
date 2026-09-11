# -*- coding: utf-8 -*-
"""虚拟化宿主机识别工具。

用于 MAC 表 / LLDP 发现中区分两类“端口上出现大量 MAC”的场景：
- 真级联：交换机互联口，对端是另一台交换机，MAC 多为交换机/终端厂商 OUI；
- 虚拟化宿主机上行口：对端是物理服务器，端口上同时出现宿主机物理网卡 MAC
  和大量虚拟机网卡 MAC（VMware / KVM / Hyper-V / Xen / VirtualBox 等已知 OUI）。

另外提供 LLDP 能力位（lldpRemSysCapEnabled）分类，把对端区分为交换机/路由器/
主机，用于“级联 vs 服务器”的最终判定。
"""

# 常见虚拟化平台虚拟网卡的 MAC OUI 前缀（前 6 位十六进制，小写）
VM_MAC_PREFIXES = {
    '005056': 'vmware',      # VMware 默认虚拟网卡（vmxnet/e1000）
    '000c29': 'vmware',      # VMware 虚拟机默认生成
    '000569': 'vmware',      # VMware ESXi/vSphere 相关
    '050056': 'vmware',      # VMware vmxnet3（本地管理位）
    '00155d': 'hyperv',      # Microsoft Hyper-V 默认虚拟网卡
    '00163e': 'xen',         # Xen / Citrix XenServer
    '525400': 'kvm',         # QEMU/KVM 默认虚拟网卡
    '080027': 'virtualbox',  # Oracle VirtualBox 默认虚拟网卡
    '001c42': 'parallels',   # Parallels Desktop
}

# 通过 sysDescr / LLDP sysDesc 识别虚拟化平台的常见关键字
HYPERVISOR_SYSDESC_KEYWORDS = [
    ('vmware', ['vmware', 'esxi', 'vsphere']),
    ('hyperv', ['hyper-v', 'hyperv', 'windows hyper']),
    ('kvm', ['kvm', 'qemu']),
    ('proxmox', ['proxmox', 'pve']),
    ('xen', ['xenserver', 'xen server', 'citrix']),
    ('virtualbox', ['virtualbox']),
    ('parallels', ['parallels']),
]


def normalize_mac(mac):
    """标准化 MAC 为 12 位小写十六进制（无分隔符）。"""
    if not mac:
        return ''
    return ''.join(c for c in str(mac).lower() if c in '0123456789abcdef')


def format_mac(mac):
    """格式化为 00:11:22:33:44:55 显示格式。"""
    norm = normalize_mac(mac)
    if len(norm) == 12:
        return ':'.join(norm[i:i + 2] for i in range(0, 12, 2))
    return mac or ''


def is_vm_mac(mac):
    """判断 MAC 是否属于已知虚拟化平台虚拟网卡。

    返回 (is_vm: bool, platform: str)
    """
    norm = normalize_mac(mac)
    if len(norm) != 12:
        return False, ''
    oui = norm[:6]
    platform = VM_MAC_PREFIXES.get(oui, '')
    return bool(platform), platform


def detect_hypervisor_platform(text):
    """从 sysDescr / LLDP sysDesc 等文本中识别虚拟化平台。

    返回平台标识（vmware/kvm/proxmox/hyperv/xen/virtualbox/parallels）或空串。
    """
    if not text:
        return ''
    low = str(text).lower()
    for platform, keywords in HYPERVISOR_SYSDESC_KEYWORDS:
        for kw in keywords:
            if kw in low:
                return platform
    return ''


def classify_port_macs(macs):
    """按端口上学习到的 MAC 集合判定端口类型。

    规则：
    - 0~1 个 MAC        -> leaf（终端直连口）
    - >=2 个 MAC，含 VM OUI -> hypervisor（虚拟化宿主机上行口）
    - >=2 个 MAC，无 VM OUI -> switch_cascade（交换机级联/上行口）

    返回 dict：
        class           leaf / hypervisor / switch_cascade
        vm_macs         虚拟网卡 MAC 列表
        vm_count        虚拟网卡数量
        physical_macs   非虚拟网卡 MAC 列表（宿主机物理网卡候选）
        platform        识别到的虚拟化平台（多个时取第一个，可能为空）
    """
    result = {
        'class': 'leaf',
        'vm_macs': [],
        'vm_count': 0,
        'physical_macs': [],
        'platform': '',
    }
    if not macs:
        return result

    seen = set()
    unique = []
    for m in macs:
        norm = normalize_mac(m)
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(m)
    if len(unique) <= 1:
        result['physical_macs'] = unique
        return result

    platforms = set()
    for m in unique:
        is_vm, platform = is_vm_mac(m)
        if is_vm:
            result['vm_macs'].append(m)
            if platform:
                platforms.add(platform)
        else:
            result['physical_macs'].append(m)
    result['vm_count'] = len(result['vm_macs'])
    result['platform'] = sorted(platforms)[0] if platforms else ''

    if result['vm_count'] > 0:
        result['class'] = 'hypervisor'
    else:
        result['class'] = 'switch_cascade'
        result['physical_macs'] = unique
    return result


def pick_physical_nic_mac(macs, arp_ip_to_mac=None):
    """从端口 MAC 集合中挑出宿主机物理网卡 MAC。

    优先顺序：ARP 表中有 IP 的 MAC > 非虚拟网卡 MAC > 任意 MAC。
    返回原始格式 MAC；无可用 MAC 时返回空串。
    """
    norm_to_raw = {}
    for m in macs or []:
        norm = normalize_mac(m)
        if len(norm) == 12:
            norm_to_raw[norm] = m
    if not norm_to_raw:
        return ''

    if arp_ip_to_mac:
        for norm, raw in norm_to_raw.items():
            if norm in arp_ip_to_mac:
                return raw

    non_vm = [raw for raw in norm_to_raw.values() if not is_vm_mac(raw)[0]]
    if non_vm:
        return non_vm[0]
    return next(iter(norm_to_raw.values()))


def classify_lldp_capabilities(cap_value):
    """按 LLDP 能力位（lldpRemSysCapEnabled / cap_enabled）分类对端类型。

    LLDP-MIB 能力位定义（从 bit0 起）：
        other=1, repeater=2, macBridge=4, wlanAP=8, router=16,
        telephone=32, docsis=64, station(host)=128
    交换机通常使能 macBridge（=4），服务器/主机使能 station（=128）。
    返回 switch / router / host / repeater / unknown。
    """
    try:
        val = int(str(cap_value or 0).strip())
    except (TypeError, ValueError):
        return 'unknown'
    if val & 4:
        return 'switch'       # macBridge -> 交换机（含级联口对端）
    if val & 16:
        return 'router'
    if val & 128:
        return 'host'         # station -> 服务器/终端
    if val & 2:
        return 'repeater'
    return 'unknown'
