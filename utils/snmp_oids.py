# -*- coding: utf-8 -*-
"""SNMP OID 常量库（RFC 公开规范，无授权问题）。

覆盖网管平台常用 MIB：
  - SNMPv2-MIB     系统基础信息（sysDescr/sysObjectID/sysName...）
  - IF-MIB         接口表（32/64 位计数器、状态、速率）
  - ENTITY-MIB     物理实体表（机箱/板卡/电源/风扇/序列号）
  - LLDP-MIB       802.1AB 邻居发现
  - CISCO-CDP-MIB  Cisco CDP 邻居缓存
  - BRIDGE-MIB     dot1d 桥表（FDB/MAC、端口映射）
  - Q-BRIDGE-MIB   802.1Q VLAN 表
  - IP-MIB / ARP   ipNetToMedia / ipNetToPhysical（ARP 表）
  - HOST-RESOURCES 服务器主机资源（存储/进程/CPU）
  - UCD-SNMP-MIB   net-snmp 扩展（CPU/内存/磁盘）
  - EtherLike-MIB  以太网错包统计
  - BGP4-MIB       BGP 对等体状态
  - OSPF-MIB       OSPF 邻居状态

注意：列号均依据 RFC 原文核实（OSPF 邻居表列序已对照 oid-base.com 校验）。
"""

# ============================================================
# SNMPv2-MIB (RFC 3418) — 系统组，单值 OID 以 .0 结尾
# ============================================================
SYS = {
    'descr':          '1.3.6.1.2.1.1.1.0',   # sysDescr
    'object_id':      '1.3.6.1.2.1.1.2.0',   # sysObjectID（厂商识别主依据）
    'up_time':        '1.3.6.1.2.1.1.3.0',   # sysUpTime
    'contact':        '1.3.6.1.2.1.1.4.0',   # sysContact
    'name':           '1.3.6.1.2.1.1.5.0',   # sysName
    'location':       '1.3.6.1.2.1.1.6.0',   # sysLocation
    'services':       '1.3.6.1.2.1.1.7.0',   # sysServices（L2=2,L3=4 位掩码）
}
SYS_DESCR = SYS['descr']
SYS_OBJECT_ID = SYS['object_id']
SYS_NAME = SYS['name']
SYS_LOCATION = SYS['location']
SYS_SERVICES = SYS['services']

# ============================================================
# IF-MIB (RFC 2863) — 接口表
# ============================================================
# ifTable（32 位计数器，索引 ifIndex）
IF_TABLE = '1.3.6.1.2.1.2.2.1'
IF = {
    'index':          IF_TABLE + '.1',    # ifIndex
    'descr':          IF_TABLE + '.2',    # ifDescr
    'type':           IF_TABLE + '.3',    # ifType
    'mtu':            IF_TABLE + '.4',    # ifMtu
    'speed':          IF_TABLE + '.5',    # ifSpeed（bps，32位溢出用 ifHighSpeed）
    'phys_address':   IF_TABLE + '.6',    # ifPhysAddress（MAC）
    'admin_status':   IF_TABLE + '.7',    # ifAdminStatus 1=up 2=down 3=testing
    'oper_status':    IF_TABLE + '.8',    # ifOperStatus 1=up 2=down ...
    'last_change':    IF_TABLE + '.9',    # ifLastChange
    'in_octets':      IF_TABLE + '.10',   # ifInOctets
    'in_ucast_pkts':  IF_TABLE + '.11',   # ifInUcastPkts
    'in_nucast_pkts': IF_TABLE + '.12',   # ifInNUcastPkts（已废弃）
    'in_discards':    IF_TABLE + '.13',   # ifInDiscards
    'in_errors':      IF_TABLE + '.14',   # ifInErrors
    'out_octets':     IF_TABLE + '.16',   # ifOutOctets
    'out_ucast_pkts': IF_TABLE + '.17',   # ifOutUcastPkts
    'out_errors':     IF_TABLE + '.20',   # ifOutErrors
    'out_qlen':       IF_TABLE + '.21',   # ifOutQLen（已废弃）
    'specific':       IF_TABLE + '.22',   # ifSpecific（已废弃）
}
# ifXTable（64 位计数器 + 扩展信息，索引 ifIndex）
IFX_TABLE = '1.3.6.1.2.1.31.1.1.1'
IFX = {
    'name':               IFX_TABLE + '.1',    # ifName（如 GigabitEthernet0/0/1）
    'in_multicast_pkts':  IFX_TABLE + '.2',
    'in_broadcast_pkts':  IFX_TABLE + '.3',
    'out_multicast_pkts': IFX_TABLE + '.4',
    'out_broadcast_pkts': IFX_TABLE + '.5',
    'hc_in_octets':       IFX_TABLE + '.6',    # ifHCInOctets（64位，优先用）
    'hc_in_ucast_pkts':   IFX_TABLE + '.7',
    'hc_in_discards':     IFX_TABLE + '.8',
    'hc_in_errors':       IFX_TABLE + '.9',
    'hc_out_octets':      IFX_TABLE + '.10',   # ifHCOutOctets
    'hc_out_ucast_pkts':  IFX_TABLE + '.11',
    'hc_out_discards':    IFX_TABLE + '.12',
    'hc_out_errors':      IFX_TABLE + '.13',
    'link_up_down_trap':  IFX_TABLE + '.14',
    'high_speed':         IFX_TABLE + '.15',   # ifHighSpeed（Mbps）
    'promiscuous_mode':   IFX_TABLE + '.16',
    'connector_present':  IFX_TABLE + '.17',
    'alias':              IFX_TABLE + '.18',   # ifAlias（端口描述）
}
IF_MIB_DESCR = IF['descr']      # 旧名兼容：ifDescr
IF_MIB_NAME = IF['descr']       # 旧名兼容：历史上即指向 ifDescr
IF_NAME = IFX['name']           # 真正的 ifName（ifXTable）

# ============================================================
# ENTITY-MIB (RFC 4133) — 物理实体表（硬件资产采集核心）
# ============================================================
ENT_PHYSICAL_TABLE = '1.3.6.1.2.1.47.1.1.1.1'
ENTITY = {
    'index':          ENT_PHYSICAL_TABLE + '.1',   # entPhysicalIndex
    'descr':          ENT_PHYSICAL_TABLE + '.2',   # entPhysicalDescr
    'vendor_type':    ENT_PHYSICAL_TABLE + '.3',   # entPhysicalVendorType
    'contained_in':   ENT_PHYSICAL_TABLE + '.4',   # entPhysicalContainedIn（父子关系）
    'class':          ENT_PHYSICAL_TABLE + '.5',   # entPhysicalClass（见 ENTITY_CLASS）
    'parent_rel_pos': ENT_PHYSICAL_TABLE + '.6',   # entPhysicalParentRelPos
    'name':           ENT_PHYSICAL_TABLE + '.7',   # entPhysicalName（如 Power Supply 1）
    'hardware_rev':   ENT_PHYSICAL_TABLE + '.8',   # entPhysicalHardwareRev
    'firmware_rev':   ENT_PHYSICAL_TABLE + '.9',   # entPhysicalFirmwareRev
    'software_rev':   ENT_PHYSICAL_TABLE + '.10',  # entPhysicalSoftwareRev
    'serial_num':     ENT_PHYSICAL_TABLE + '.11',  # entPhysicalSerialNum
    'mfg_name':       ENT_PHYSICAL_TABLE + '.12',  # entPhysicalMfgName
    'model_name':     ENT_PHYSICAL_TABLE + '.13',  # entPhysicalModelName
    'alias':          ENT_PHYSICAL_TABLE + '.14',
    'asset_id':       ENT_PHYSICAL_TABLE + '.15',  # entPhysicalAssetID
    'is_fru':         ENT_PHYSICAL_TABLE + '.16',  # entPhysicalIsFRU 1=true
}
# entPhysicalClass 枚举
ENTITY_CLASS = {
    1: 'other', 2: 'unknown', 3: 'chassis', 4: 'backplane', 5: 'container',
    6: 'powerSupply', 7: 'fan', 8: 'sensor', 9: 'module', 10: 'port',
    11: 'stack', 12: 'cpu',
}
# entPhysicalClass 反查（名称 → 枚举值）
ENTITY_CLASS_CODE = {v: k for k, v in ENTITY_CLASS.items()}
# 实体状态表（ENTITY-STATE-MIB，部分厂商支持）
ENTITY_STATE = {
    'admin_state':   '1.3.6.1.2.1.47.1.2.1.1.2',  # entStateAdmin
    'oper_state':    '1.3.6.1.2.1.47.1.2.1.1.3',  # entStateOper
    'standby_state': '1.3.6.1.2.1.47.1.2.1.1.6',  # entStateStandby
}

# ============================================================
# LLDP-MIB (IEEE 802.1AB) — 邻居发现
# ============================================================
LLDP_ROOT = '1.0.8802.1.1.2.1'
LLDP = {
    # 本地信息
    'loc_chassis_id_subtype': LLDP_ROOT + '.3.1.0',  # lldpLocChassisIdSubtype
    'loc_chassis_id':         LLDP_ROOT + '.3.2.0',  # lldpLocChassisId
    'loc_sys_name':           LLDP_ROOT + '.3.3.0',  # lldpLocSysName
    'loc_sys_desc':           LLDP_ROOT + '.3.4.0',  # lldpLocSysDesc
    # 本地端口表 lldpLocPortTable（索引 lldpLocPortNum）
    'loc_port_id_subtype':    LLDP_ROOT + '.3.7.1.1',
    'loc_port_id':            LLDP_ROOT + '.3.7.1.2',
    'loc_port_desc':          LLDP_ROOT + '.3.7.1.3',
    # 远端表 lldpRemTable（索引 lldpRemTimeMark+lldpRemLocalPortNum+lldpRemIndex）
    'rem_chassis_id_subtype': LLDP_ROOT + '.4.1.1.1',
    'rem_chassis_id':         LLDP_ROOT + '.4.1.1.2',
    'rem_port_id_subtype':    LLDP_ROOT + '.4.1.1.3',
    'rem_port_id':            LLDP_ROOT + '.4.1.1.4',
    'rem_port_desc':          LLDP_ROOT + '.4.1.1.5',
    'rem_sys_name':           LLDP_ROOT + '.4.1.1.6',
    'rem_sys_desc':           LLDP_ROOT + '.4.1.1.7',
    'rem_sys_cap_supported':  LLDP_ROOT + '.4.1.1.8',  # 能力位（L2桥/L3路由等）
    'rem_sys_cap_enabled':    LLDP_ROOT + '.4.1.1.9',
    # 统计
    'stats_rem_tables_ageouts': LLDP_ROOT + '.2.2.2.0',
}
LLDP_REM_TABLE = LLDP_ROOT + '.4.1.1'
LLDP_LOC_PORT_ID = LLDP['loc_port_id']        # 旧名兼容
LLDP_LOC_PORT_DESC = LLDP['loc_port_desc']    # 旧名兼容

# ============================================================
# CISCO-CDP-MIB — Cisco 发现协议缓存
# ============================================================
CDP_ROOT = '1.3.6.1.4.1.9.9.23'
CDP = {
    'global_run':   CDP_ROOT + '.1.3.1.0',          # cdpGlobalRun 1=enabled
    # cdpCacheTable（索引 cdpCacheIfIndex+cdpCacheDeviceIndex）
    'cache_device_id':   CDP_ROOT + '.1.2.1.1.6',   # cdpCacheDeviceId
    'cache_device_port': CDP_ROOT + '.1.2.1.1.7',   # cdpCacheDevicePort
    'cache_platform':    CDP_ROOT + '.1.2.1.1.8',   # cdpCachePlatform
    'cache_version':     CDP_ROOT + '.1.2.1.1.5',   # cdpCacheVersion
    'cache_duplex':      CDP_ROOT + '.1.2.1.1.11',  # cdpCacheDuplex
    'cache_appearance':  CDP_ROOT + '.1.2.1.1.10',  # cdpCacheApplianceID
}
CDP_CACHE_TABLE = CDP_ROOT + '.1.2.1.1'

# ============================================================
# BRIDGE-MIB (RFC 4188) — dot1d 桥接
# ============================================================
BRIDGE_ROOT = '1.3.6.1.2.1.17'
BRIDGE = {
    'base_bridge_address': BRIDGE_ROOT + '.1.1.0',   # dot1dBaseBridgeAddress（桥MAC）
    'base_num_ports':      BRIDGE_ROOT + '.1.2.0',
    'base_type':           BRIDGE_ROOT + '.1.3.0',
    # dot1dBasePortTable（索引 dot1dBasePort）— 桥端口 → ifIndex 映射
    'base_port_ifindex':   BRIDGE_ROOT + '.1.4.3.1.2',
    # dot1dTpFdbTable（索引 MAC）— FDB/MAC 表
    'fdb_address':         BRIDGE_ROOT + '.4.3.1.1',  # dot1dTpFdbAddress
    'fdb_port':            BRIDGE_ROOT + '.4.3.1.2',  # dot1dTpFdbPort（dot1dBasePort）
    'fdb_status':          BRIDGE_ROOT + '.4.3.1.3',  # 3=learned 4=self 5=mgmt
    # dot1dTpPortTable（索引 dot1dTpPort）
    'tp_port_in_frames':   BRIDGE_ROOT + '.4.4.1.1',  # dot1dTpPortInFrames
    'tp_port_out_frames':  BRIDGE_ROOT + '.4.4.1.2',
    'tp_port_in_discards': BRIDGE_ROOT + '.4.4.1.3',
    # 生成树
    'stp_port_state':      BRIDGE_ROOT + '.2.15.1.3',  # dot1dStpPortState
    'stp_port_role':       BRIDGE_ROOT + '.2.17.1.2',  # dot1dStpPortRole（扩展）
}
DOT1D_FDB_TABLE = BRIDGE_ROOT + '.4.3.1'

# ============================================================
# Q-BRIDGE-MIB (RFC 4363) — 802.1Q VLAN
# ============================================================
QBRIDGE_ROOT = '1.3.6.1.2.1.17.7'
QBRIDGE = {
    # dot1qVlanCurrentTable
    'vlan_current_egress_ports':   QBRIDGE_ROOT + '.1.2.1.1.2',
    # dot1qVlanStaticTable（索引 VLAN ID）
    'vlan_static_name':            QBRIDGE_ROOT + '.1.4.3.1.1',  # dot1qVlanStaticName
    'vlan_static_egress_ports':    QBRIDGE_ROOT + '.1.4.3.1.2',
    'vlan_static_untagged_ports':  QBRIDGE_ROOT + '.1.4.3.1.3',
    'vlan_static_row_status':      QBRIDGE_ROOT + '.1.4.3.1.5',
    # dot1qPortVlanTable（索引 ifIndex）
    'port_pvid':                   QBRIDGE_ROOT + '.1.4.5.1.1',  # dot1qPvid
    'port_acceptable_frame_types': QBRIDGE_ROOT + '.1.4.5.1.3',  # 2=admitOnlyVlanTagged（trunk）
    'port_ingress_filtering':      QBRIDGE_ROOT + '.1.4.5.1.4',
    # dot1qFdbTable（VLAN 感知 FDB）
    'fdb_id':                      QBRIDGE_ROOT + '.1.2.3.1.1',
}
DOT1Q_VLAN_STATIC_NAME = QBRIDGE['vlan_static_name']

# ============================================================
# IP-MIB (RFC 4293) / ARP 表
# ============================================================
IP_MIB = {
    # ipNetToPhysicalTable（新，IPv4+IPv6；索引 ifIndex+协议+地址）
    'net_to_physical_phys_address': '1.3.6.1.2.1.4.35.1.2',
    'net_to_physical_state':        '1.3.6.1.2.1.4.35.1.4',   # 1=reachable 等
    # ipNetToMediaTable（旧，仅 IPv4；索引 ifIndex+IP）
    'net_to_media_ifindex':         '1.3.6.1.2.1.4.22.1.1',
    'net_to_media_phys_address':    '1.3.6.1.2.1.4.22.1.2',   # ARP: IP → MAC
    'net_to_media_net_address':     '1.3.6.1.2.1.4.22.1.3',
    'net_to_media_type':            '1.3.6.1.2.1.4.22.1.4',   # 3=dynamic 4=static
    # IPv4 转发表（下一跳，拓扑辅助）
    'ip_route_dest':                '1.3.6.1.2.1.4.21.1.1',
    'ip_route_next_hop':            '1.3.6.1.2.1.4.21.1.7',
    'ip_route_ifindex':             '1.3.6.1.2.1.4.21.1.2',
    'ip_route_mask':                '1.3.6.1.2.1.4.21.1.11',
    # ipAdEntAddrIfIndex：本机接口 IP（索引 IP）
    'ip_addr_entry_ifindex':        '1.3.6.1.2.1.4.20.1.2',
    'ip_addr_entry_net_mask':       '1.3.6.1.2.1.4.20.1.3',
}
IP_NET_TO_MEDIA_PHYS_ADDRESS = IP_MIB['net_to_media_phys_address']
IP_NET_TO_MEDIA_NET_ADDRESS = IP_MIB['net_to_media_net_address']

# ============================================================
# HOST-RESOURCES-MIB (RFC 2790) — 服务器主机资源
# ============================================================
HOST_RESOURCES = {
    'system_uptime':          '1.3.6.1.2.1.25.1.1.0',  # hrSystemUptime
    'system_date':            '1.3.6.1.2.1.25.1.2.0',  # hrSystemDate
    'system_users':           '1.3.6.1.2.1.25.1.5.0',  # hrSystemNumUsers
    'system_processes':       '1.3.6.1.2.1.25.1.6.0',  # hrSystemProcesses
    'memory_size':            '1.3.6.1.2.1.25.2.2.0',  # hrMemorySize（KB）
    # hrStorageTable（索引 hrStorageIndex）
    'storage_type':           '1.3.6.1.2.1.25.2.3.1.2',
    'storage_descr':          '1.3.6.1.2.1.25.2.3.1.3',
    'storage_allocation_units': '1.3.6.1.2.1.25.2.3.1.4',
    'storage_size':           '1.3.6.1.2.1.25.2.3.1.5',
    'storage_used':           '1.3.6.1.2.1.25.2.3.1.6',
    'storage_allocation_failures': '1.3.6.1.2.1.25.2.3.1.7',
    # hrDeviceTable（索引 hrDeviceIndex）
    'device_type':            '1.3.6.1.2.1.25.3.1.1.2',
    'device_descr':           '1.3.6.1.2.1.25.3.1.1.3',  # CPU 型号等
    'device_id':              '1.3.6.1.2.1.25.3.1.1.4',
    'device_status':          '1.3.6.1.2.1.25.3.1.1.5',  # 2=unknown 3=ok 6=error
    # hrProcessorTable（索引 hrDeviceIndex）
    'processor_load':         '1.3.6.1.2.1.25.3.3.1.2',  # hrProcessorLoad（%）
    # hrSWRunTable（进程表，索引 hrSWRunIndex）
    'sw_run_name':            '1.3.6.1.2.1.25.4.2.1.2',
    'sw_run_path':            '1.3.6.1.2.1.25.4.2.1.4',
    'sw_run_status':          '1.3.6.1.2.1.25.4.2.1.7',  # 1=running 2=runnable 4=invalid
    # hrSWInstalledTable（已安装软件）
    'sw_installed_name':      '1.3.6.1.2.1.25.6.3.1.2',
    'sw_installed_type':      '1.3.6.1.2.1.25.6.3.1.3',
}
HR_STORAGE_TABLE = '1.3.6.1.2.1.25.2.3.1'

# ============================================================
# UCD-SNMP-MIB — net-snmp / Linux 采集
# ============================================================
UCD_ROOT = '1.3.6.1.4.1.2021'
UCD = {
    # 系统负载 laTable（索引 laIndex 1/5/15 分钟）
    'la_names':       UCD_ROOT + '.10.1.1',   # laNames（Load-1/Load-5/Load-15）
    'la_load':        UCD_ROOT + '.10.1.3',   # laLoad
    'la_load_int':    UCD_ROOT + '.10.1.5',   # laLoadInt（×100）
    # 内存
    'mem_total_swap': UCD_ROOT + '.4.3.0',
    'mem_total_real': UCD_ROOT + '.4.5.0',    # memTotalReal（KB）
    'mem_avail_real': UCD_ROOT + '.4.6.0',    # memAvailReal（KB）
    'mem_total_free': UCD_ROOT + '.4.11.0',
    'mem_buffer':     UCD_ROOT + '.4.14.0',
    'mem_cached':     UCD_ROOT + '.4.15.0',
    # CPU（百分比，1/5/15 分钟均值）
    'ss_cpu_user':    UCD_ROOT + '.11.9.0',
    'ss_cpu_system':  UCD_ROOT + '.11.10.0',
    'ss_cpu_idle':    UCD_ROOT + '.11.11.0',
    # 磁盘 dskTable（需 snmpd.conf 配置 disk 挂载点）
    'dsk_path':       UCD_ROOT + '.9.1.2',
    'dsk_total':      UCD_ROOT + '.9.1.7',    # dskTotal（分配单元）
    'dsk_avail':      UCD_ROOT + '.9.1.8',    # dskAvail
    'dsk_used':       UCD_ROOT + '.9.1.9',    # dskUsed
    'dsk_percent':    UCD_ROOT + '.9.1.10',   # dskPercent
    'dsk_percent_node': UCD_ROOT + '.9.1.11', # inode 使用率
    # IO
    'ss_io_read':     UCD_ROOT + '.11.51.0',  # ssIORawData
    'ss_io_write':    UCD_ROOT + '.11.52.0',  # ssIOWRawData
}

# ============================================================
# EtherLike-MIB (RFC 3635) — 以太网错包统计（索引 ifIndex）
# ============================================================
DOT3_STATS_TABLE = '1.3.6.1.2.1.10.7.2.1'
ETHERLIKE = {
    'alignment_errors':      DOT3_STATS_TABLE + '.2',
    'fcs_errors':            DOT3_STATS_TABLE + '.3',   # CRC 校验错（链路质量核心指标）
    'single_collision':      DOT3_STATS_TABLE + '.4',
    'multiple_collision':    DOT3_STATS_TABLE + '.5',
    'deferred_transmissions': DOT3_STATS_TABLE + '.7',
    'late_collisions':       DOT3_STATS_TABLE + '.8',
    'excessive_collisions':  DOT3_STATS_TABLE + '.9',
    'internal_mac_tx_errors': DOT3_STATS_TABLE + '.10',
    'carrier_sense_errors':  DOT3_STATS_TABLE + '.11',
    'frame_too_longs':       DOT3_STATS_TABLE + '.13',
    'internal_mac_rx_errors': DOT3_STATS_TABLE + '.16',
}

# ============================================================
# BGP4-MIB (RFC 4273) — BGP 对等体（索引 bgpPeerRemoteAddr）
# ============================================================
BGP_ROOT = '1.3.6.1.2.1.15'
BGP = {
    'local_as':          BGP_ROOT + '.1.0',        # bgpLocalAs
    # bgpPeerTable
    'peer_identifier':   BGP_ROOT + '.3.1.1',
    'peer_state':        BGP_ROOT + '.3.1.2',      # 1=idle 2=connect 3=active 4=opensent 5=openconfirm 6=established
    'peer_admin_status': BGP_ROOT + '.3.1.3',
    'peer_local_addr':   BGP_ROOT + '.3.1.5',
    'peer_local_port':   BGP_ROOT + '.3.1.6',
    'peer_remote_addr':  BGP_ROOT + '.3.1.7',      # 索引本身
    'peer_remote_port':  BGP_ROOT + '.3.1.8',
    'peer_remote_as':    BGP_ROOT + '.3.1.9',
    'peer_in_updates':   BGP_ROOT + '.3.1.10',
    'peer_out_updates':  BGP_ROOT + '.3.1.11',
    'peer_in_total':     BGP_ROOT + '.3.1.12',
    'peer_out_total':    BGP_ROOT + '.3.1.13',
    'peer_last_error':   BGP_ROOT + '.3.1.15',
    'peer_fsm_est_time': BGP_ROOT + '.3.1.16',     # bgpPeerFsmEstablishedTime
}
BGP_PEER_TABLE = BGP_ROOT + '.3.1'
BGP_PEER_STATE_NAMES = {
    1: 'idle', 2: 'connect', 3: 'active', 4: 'opensent',
    5: 'openconfirm', 6: 'established',
}

# ============================================================
# OSPF-MIB (RFC 4750) — OSPF 邻居/接口
# （邻居表列序已对照 oid-base.com 逐列核实：
#   1=IpAddr 2=AddressLessIndex 3=RtrId 4=Options 5=Priority
#   6=State 7=Events 8=LsRetransQLen 9=NbmaNbrStatus ...）
# ============================================================
OSPF_ROOT = '1.3.6.1.2.1.14'
OSPF = {
    'router_id':        OSPF_ROOT + '.1.1.0',        # ospfRouterId
    'admin_status':     OSPF_ROOT + '.1.2.0',        # ospfAdminStat 1=enabled
    'version_number':   OSPF_ROOT + '.1.3.0',
    'area_bdr_rtr_status': OSPF_ROOT + '.1.4.0',
    'as_bdr_rtr_status':   OSPF_ROOT + '.1.5.0',
    # ospfNbrTable（索引 ospfNbrIpAddr+ospfNbrAddressLessIndex）
    'nbr_ip_addr':      OSPF_ROOT + '.10.1.1',
    'nbr_rtr_id':       OSPF_ROOT + '.10.1.3',
    'nbr_state':        OSPF_ROOT + '.10.1.6',       # OSPF 邻居状态（核心）
    'nbr_events':       OSPF_ROOT + '.10.1.7',
    'nbr_ls_retrans_qlen': OSPF_ROOT + '.10.1.8',
    # ospfIfTable（接口级）
    'if_area_id':       OSPF_ROOT + '.7.1.1.2',      # ospfIfAreaId
    'if_type':          OSPF_ROOT + '.7.1.1.3',
    'if_state':         OSPF_ROOT + '.7.1.1.12',     # ospfIfState
}
OSPF_NBR_TABLE = OSPF_ROOT + '.10.1'
OSPF_NBR_STATE_NAMES = {
    1: 'down', 2: 'attempt', 3: 'init', 4: 'twoWay',
    5: 'exchangeStart', 6: 'exchange', 7: 'loading', 8: 'full',
}
