#from pysnmp.hlapi import *
from typing import Dict, List, Any
import ipaddress
from datetime import datetime
from utils.utils import is_valid_ip, parse_ip_range

class SNMPScanner:
    def __init__(self, ip, community='public', version=2):
        self.ip = ip
        self.community = community
        self.version = version

    def get_lldp_neighbors(self):
        """通过LLDP获取邻居信息（SNMP OID：1.0.8802.1.1.2.1.4.1.1）"""
        neighbors = []
        # LLDP本地接口OID：1.0.8802.1.1.2.1.3.7.1.3
        # LLDP远端设备名OID：1.0.8802.1.1.2.1.4.1.1.9
        # LLDP远端接口OID：1.0.8802.1.1.2.1.4.1.1.12
        oids = [
            '1.0.8802.1.1.2.1.3.7.1.3',  # 本地接口名
            '1.0.8802.1.1.2.1.4.1.1.9', # 远端设备名
            '1.0.8802.1.1.2.1.4.1.1.12' # 远端接口名
        ]
        try:
            for errorIndication, errorStatus, errorIndex, varBinds in nextCmd(
                SnmpEngine(),
                CommunityData(self.community, mpModel=1 if self.version == 2 else 0),
                UdpTransportTarget((self.ip, 161)),
                ContextData(),
                ObjectType(ObjectIdentity(oids[0])),
                ObjectType(ObjectIdentity(oids[1])),
                ObjectType(ObjectIdentity(oids[2])),
                lexicographicMode=False
            ):
                if errorIndication:
                    print(f"LLDP SNMP错误: {errorIndication}")
                    break
                if errorStatus:
                    print(f"LLDP SNMP错误: {errorStatus.prettyPrint()}")
                    break
                
                # 解析返回值
                local_if = varBinds[0][1].prettyPrint()
                remote_device = varBinds[1][1].prettyPrint()
                remote_if = varBinds[2][1].prettyPrint()
                
                # 清理接口名（去除多余字符）
                local_if = self._clean_interface_name(local_if)
                remote_if = self._clean_interface_name(remote_if)
                
                neighbors.append({
                    'protocol': 'LLDP',
                    'local_interface': local_if,
                    'remote_device_name': remote_device,
                    'remote_interface': remote_if
                })
        except Exception as e:
            print(f"获取LLDP邻居失败: {str(e)}")
        return neighbors

    def get_cdp_neighbors(self):
        """通过CDP获取邻居信息（SNMP OID：1.3.6.1.4.1.9.9.23.1.2.1.1）"""
        neighbors = []
        # CDP本地接口OID：1.3.6.1.4.1.9.9.23.1.2.1.1.3
        # CDP远端设备名OID：1.3.6.1.4.1.9.9.23.1.2.1.1.6
        # CDP远端接口OID：1.3.6.1.4.1.9.9.23.1.2.1.1.7
        oids = [
            '1.3.6.1.4.1.9.9.23.1.2.1.1.3',  # 本地接口
            '1.3.6.1.4.1.9.9.23.1.2.1.1.6',  # 远端设备名
            '1.3.6.1.4.1.9.9.23.1.2.1.1.7'   # 远端接口
        ]
        try:
            for errorIndication, errorStatus, errorIndex, varBinds in nextCmd(
                SnmpEngine(),
                CommunityData(self.community, mpModel=1 if self.version == 2 else 0),
                UdpTransportTarget((self.ip, 161)),
                ContextData(),
                ObjectType(ObjectIdentity(oids[0])),
                ObjectType(ObjectIdentity(oids[1])),
                ObjectType(ObjectIdentity(oids[2])),
                lexicographicMode=False
            ):
                if errorIndication or errorStatus:
                    break
                
                local_if = varBinds[0][1].prettyPrint()
                remote_device = varBinds[1][1].prettyPrint()
                remote_if = varBinds[2][1].prettyPrint()
                
                local_if = self._clean_interface_name(local_if)
                remote_if = self._clean_interface_name(remote_if)
                
                neighbors.append({
                    'protocol': 'CDP',
                    'local_interface': local_if,
                    'remote_device_name': remote_device,
                    'remote_interface': remote_if
                })
        except Exception as e:
            print(f"获取CDP邻居失败: {str(e)}")
        return neighbors

    def _clean_interface_name(self, if_name):
        """清理接口名（如去除OID后缀、多余空格）"""
        if_name = re.sub(r'\.\d+$', '', if_name)  # 去除数字后缀
        if_name = if_name.strip()
        # 映射常见接口缩写（可选）
        if_mapping = {
            'GigabitEthernet': 'Gi',
            'FastEthernet': 'Fa',
            'Ethernet': 'Eth'
        }
        for full, short in if_mapping.items():
            if_name = if_name.replace(full, short)
        return if_name
