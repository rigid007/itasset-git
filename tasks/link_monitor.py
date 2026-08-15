# tasks/link_monitor.py
"""
链路状态监控模块
支持通过SNMP、LLDP、Ping等多种方式检测链路状态
"""
import json
import time
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask
from sqlalchemy import and_
from sqlalchemy.orm import sessionmaker, scoped_session

from extensions import db
from models.models import (
    Device, Interface, ConnectionPath, 
    DeviceMonitorLog, AlertEvent, DiscoveryResult
)
from models.config_models import SystemLog
from utils.utils import ping_device, snmp_get, snmp_walk

# 用于从 LLDP 邻居信息中识别 AP / 无线边缘设备的特征关键词
AP_KEYWORDS = ('ap', 'access point', 'air', 'aruba', 'fitap', 'huawei ap',
               'cisco ap', 'ruckus', 'wireless', 'wlc')


class LinkMonitor:
    """链路状态监控器"""
    
    def __init__(self, app: Flask = None):
        self.app = app
        self.pool = ThreadPoolExecutor(max_workers=20)  # 原 5，提升链路检测并发
        self.snmp_timeout = 3
        self.snmp_retries = 1
        
        # 延迟初始化 Session
        self._session = None
        
        # LLDP MIB OIDs
        self.LLDP_CHASSIS_OID = '1.0.8802.1.1.2.1.4.1.1.5'
        self.LLDP_PORT_OID = '1.0.8802.1.1.2.1.4.1.1.7'
        self.LLDP_SYSNAME_OID = '1.0.8802.1.1.2.1.4.1.1.9'
        self.LLDP_SYSDESC_OID = '1.0.8802.1.1.2.1.4.1.1.10'
        
        # Interface MIB OIDs
        self.IF_NAME_OID = '1.3.6.1.2.1.2.2.1.2'
        self.IF_STATUS_OID = '1.3.6.1.2.1.2.2.1.8'
        self.IF_ADMIN_STATUS_OID = '1.3.6.1.2.1.2.2.1.7'
        self.IF_SPEED_OID = '1.3.6.1.2.1.2.2.1.5'
    
    @property
    def Session(self):
        """延迟创建 Session"""
        if self._session is None:
            try:
                if self.app:
                    with self.app.app_context():
                        self._session = scoped_session(sessionmaker(bind=db.engine))
                else:
                    self._session = scoped_session(sessionmaker(bind=db.engine))
            except Exception as e:
                print(f"创建 Session 失败: {e}")
                self._session = None
        return self._session
    
    # ==================== SNMP辅助函数 ====================
    def snmp_get_value(self, ip: str, oid: str, community: str = 'public', version: int = 2) -> Optional[str]:
        """获取SNMP值"""
        try:
            # snmp_get 的参数顺序: ip, community, version, oid, timeout
            # version 参数需要转换为字符串 '2c' 或 '1'
            ver_str = '2c' if version == 2 else '1'
            
            result = snmp_get(
                ip=ip,
                community=community,
                version=ver_str,
                oid=oid,
                timeout=self.snmp_timeout
            )
            
            print(f"    [DEBUG] snmp_get 原始返回: {repr(result)} (类型: {type(result)})")
            
            if result is None:
                return None
            
            # 处理字节类型
            if isinstance(result, bytes):
                decoded = result.decode('utf-8', errors='ignore')
                print(f"    [DEBUG] 字节解码: {repr(decoded)}")
                return decoded
            
            # 处理列表类型
            if isinstance(result, list):
                if result:
                    first = result[0]
                    if isinstance(first, bytes):
                        decoded = first.decode('utf-8', errors='ignore')
                        print(f"    [DEBUG] 列表字节解码: {repr(decoded)}")
                        return decoded
                    print(f"    [DEBUG] 列表第一个元素: {repr(first)}")
                    return str(first)
                return None
            
            # 处理元组类型
            if isinstance(result, tuple):
                if result:
                    first = result[0]
                    if isinstance(first, bytes):
                        decoded = first.decode('utf-8', errors='ignore')
                        print(f"    [DEBUG] 元组字节解码: {repr(decoded)}")
                        return decoded
                    print(f"    [DEBUG] 元组第一个元素: {repr(first)}")
                    return str(first)
                return None
            
            # 处理整数/浮点数
            if isinstance(result, (int, float)):
                print(f"    [DEBUG] 数字类型: {result}")
                return str(result)
            
            print(f"    [DEBUG] 直接转字符串: {repr(str(result))}")
            return str(result)
        except Exception as e:
            print(f"    [DEBUG] snmp_get_value 异常: {e}")
            import traceback
            traceback.print_exc()
            return None

    def snmp_walk_values(self, ip: str, oid: str, community: str = 'public', version: int = 2) -> Dict[str, str]:
        """遍历SNMP OID"""
        try:
            # snmp_walk 的参数顺序: ip, oid, community, version, timeout, retries
            ver_str = '2c' if version == 2 else '1'
            
            result = snmp_walk(
                ip=ip,
                oid=oid,
                community=community,
                version=ver_str,
                timeout=self.snmp_timeout,
                retries=self.snmp_retries
            )
            
            # 如果返回None或空
            if not result:
                return {}
            
            # snmp_walk 返回 List[Tuple[str, str]]
            if isinstance(result, list):
                converted = {}
                for item in result:
                    if isinstance(item, tuple) and len(item) >= 2:
                        oid_key = str(item[0])
                        value = str(item[1])
                        converted[oid_key] = value
                    elif isinstance(item, dict):
                        converted.update(item)
                return converted
            
            # 如果返回的是字典，直接处理
            if isinstance(result, dict):
                converted = {}
                for key, value in result.items():
                    key_str = str(key)
                    value_str = str(value)
                    converted[key_str] = value_str
                return converted
            
            return {}
            
        except Exception as e:
            print(f"    [DEBUG] snmp_walk_values 异常: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def get_port_status(self, device_ip: str, ifindex: int, 
                        community: str = 'public') -> Optional[int]:
        """获取端口操作状态 1=up, 2=down, 3=testing"""
        oid = f'{self.IF_STATUS_OID}.{ifindex}'
        print(f"  [DEBUG] 获取端口状态: {device_ip} {oid}")
        result = self.snmp_get_value(device_ip, oid, community)
        
        print(f"  [DEBUG] get_port_status 原始结果: {repr(result)}")
        
        if result is None:
            print(f"  [DEBUG] 端口状态返回 None")
            return None
        
        # 确保是字符串类型
        result_str = str(result).strip().lower()
        print(f"  [DEBUG] get_port_status 字符串: {repr(result_str)}")
        
        # 状态映射表
        status_map = {
            'up': 1,
            'down': 2,
            'testing': 3,
            '1': 1,
            '2': 2,
            '3': 3,
            '1.0': 1,
            '2.0': 2,
            '3.0': 3,
        }
        
        # 直接匹配
        if result_str in status_map:
            status = status_map[result_str]
            print(f"  [DEBUG] 状态映射: {result_str} -> {status}")
            return status
        
        # 尝试匹配 up(1) 或 down(2) 或 testing(3) 格式
        match = re.search(r'\((\d+)\)', result_str)
        if match:
            status = int(match.group(1))
            print(f"  [DEBUG] 从括号中提取端口状态: {status}")
            return status
        
        # 尝试匹配整数: 1, 2, 3
        match = re.search(r'^(\d+)$', result_str)
        if match:
            status = int(match.group(1))
            print(f"  [DEBUG] 直接匹配端口状态: {status}")
            return status
        
        # 尝试直接转换
        try:
            status = int(result_str)
            print(f"  [DEBUG] 直接转换端口状态: {status}")
            return status
        except (ValueError, TypeError):
            pass
        
        # 最后尝试从字符串中提取任何数字
        match = re.search(r'(\d+)', result_str)
        if match:
            status = int(match.group(1))
            print(f"  [DEBUG] 从字符串中提取数字: {status}")
            return status
        
        print(f"  [DEBUG] 无法解析端口状态: {repr(result_str)}")
        return None

    
    # ==================== Ping检测 ====================
    
    def ping_check(self, ip: str, timeout: int = 2) -> Tuple[bool, float]:
        """Ping检测"""
        return ping_device(ip, timeout=timeout)
    
    # ==================== 端口信息获取 ====================
    
    def get_interface_ifindex(self, device_ip: str, port_name: str, 
                              community: str = 'public') -> Optional[int]:
        """通过端口名获取ifindex"""
        try:
            print(f"  [DEBUG] 获取 {device_ip} 的接口列表...")
            interfaces = self.snmp_walk_values(device_ip, self.IF_NAME_OID, community)
            
            if not interfaces:
                print(f"  [DEBUG] 未获取到任何接口信息")
                return None
            
            if not isinstance(interfaces, dict):
                print(f"  [DEBUG] interfaces 类型不是字典: {type(interfaces)}")
                return None
            
            print(f"  [DEBUG] 获取到 {len(interfaces)} 个接口")
            
            def normalize_port_name(name):
                if not name:
                    return ''
                name = name.strip()
                return name.lower()
            
            normalized_port = normalize_port_name(port_name)
            print(f"  [DEBUG] 查找端口: {port_name} (标准化: {normalized_port})")
            
            # 精确匹配
            for oid, name in interfaces.items():
                clean_name = normalize_port_name(name)
                if clean_name == normalized_port:
                    match = re.search(r'\.(\d+)$', oid)
                    if match:
                        ifindex = int(match.group(1))
                        print(f"  [DEBUG] 精确匹配找到端口 {port_name} 的 ifindex: {ifindex}")
                        return ifindex
            
            # 模糊匹配：提取端口编号 (如 1/0/5)
            target_num_match = re.search(r'(\d+/\d+/\d+)', normalized_port)
            if target_num_match:
                target_num = target_num_match.group(1)
                print(f"  [DEBUG] 尝试端口编号匹配: {target_num}")
                for oid, name in interfaces.items():
                    clean_name = normalize_port_name(name)
                    port_num_match = re.search(r'(\d+/\d+/\d+)', clean_name)
                    if port_num_match and port_num_match.group(1) == target_num:
                        match = re.search(r'\.(\d+)$', oid)
                        if match:
                            ifindex = int(match.group(1))
                            print(f"  [DEBUG] 端口编号匹配找到端口 {port_name} 的 ifindex: {ifindex} (匹配到 {clean_name})")
                            return ifindex
            
            # 如果还是没找到，打印所有接口名称用于调试
            print(f"  [DEBUG] 未找到端口 {port_name}，可用的接口名称:")
            for oid, name in list(interfaces.items())[:20]:
                print(f"    {oid}: {name}")
            
            return None
            
        except Exception as e:
            print(f"  [DEBUG] get_interface_ifindex 异常: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    # def get_port_status(self, device_ip: str, ifindex: int, 
    #                     community: str = 'public') -> Optional[int]:
    #     """获取端口操作状态 1=up, 2=down, 3=testing"""
    #     oid = f'{self.IF_STATUS_OID}.{ifindex}'
    #     print(f"  [DEBUG] 获取端口状态: {device_ip} {oid}")
    #     result = self.snmp_get_value(device_ip, oid, community)
        
    #     if result is None:
    #         print(f"  [DEBUG] 端口状态返回 None")
    #         return None
        
    #     if isinstance(result, bytes):
    #         result = result.decode('utf-8', errors='ignore')
        
    #     if isinstance(result, list):
    #         if result:
    #             result = result[0]
    #         else:
    #             return None
        
    #     if result:
    #         try:
    #             status = int(result)
    #             print(f"  [DEBUG] 端口状态: {status} (1=up, 2=down)")
    #             return status
    #         except (ValueError, TypeError):
    #             return None
    #     return None
        
    def get_port_name(self, device_ip: str, ifindex: int, 
                      community: str = 'public') -> Optional[str]:
        """通过ifindex获取端口名"""
        oid = f'{self.IF_NAME_OID}.{ifindex}'
        return self.snmp_get_value(device_ip, oid, community)
    
    # ==================== LLDP邻居信息获取 ====================
    
    def get_lldp_neighbors(self, device_ip: str, port_name: Optional[str] = None,
                          community: str = 'public') -> List[Dict]:
        """获取LLDP邻居信息"""
        neighbors = []
        
        chassis_results = self.snmp_walk_values(device_ip, self.LLDP_CHASSIS_OID, community)
        
        if not isinstance(chassis_results, dict):
            return neighbors
        
        # 辅助函数：清理值
        def clean_value(val):
            if not val:
                return ''
            val = val.strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            if val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            return val.strip()
        
        for oid, chassis_id in chassis_results.items():
            parts = oid.split('.')
            if len(parts) < 3:
                continue
            
            try:
                ifindex = int(parts[-2])
                remote_index = int(parts[-1])
            except (ValueError, IndexError):
                continue
            
            local_port = self.get_port_name(device_ip, ifindex, community)
            if not local_port:
                continue
            
            if port_name and local_port != port_name:
                continue
            
            neighbor = {
                'local_port': local_port,
                'ifindex': ifindex,
                'remote_index': remote_index,
                'chassis_id': clean_value(chassis_id),
            }
            
            port_oid = f'{self.LLDP_PORT_OID}.0.{ifindex}.{remote_index}'
            port_id = self.snmp_get_value(device_ip, port_oid, community)
            if port_id:
                neighbor['remote_port_id'] = clean_value(port_id)
            
            sysname_oid = f'{self.LLDP_SYSNAME_OID}.0.{ifindex}.{remote_index}'
            sysname = self.snmp_get_value(device_ip, sysname_oid, community)
            if sysname:
                neighbor['remote_system_name'] = clean_value(sysname)

            # 补充采集 LLDP 系统描述，用于识别 AP 等边缘设备（SYSDESC_OID 已在类内定义）
            desc_oid = f'{self.LLDP_SYSDESC_OID}.0.{ifindex}.{remote_index}'
            sysdesc = self.snmp_get_value(device_ip, desc_oid, community)
            if sysdesc:
                neighbor['remote_sys_desc'] = clean_value(sysdesc)

            neighbors.append(neighbor)
        
        return neighbors
    
    # ==================== 设备查找 ====================
    
    def find_device_by_mac(self, mac: str, session=None) -> Optional[Device]:
        """通过MAC地址查找设备"""
        if not mac:
            return None
        mac_clean = re.sub(r'[^0-9A-Fa-f]', '', mac).upper()
        
        if session is None:
            session = db.session
        
        devices = session.query(Device).filter(Device.mac_address.isnot(None)).all()
        for device in devices:
            if not device.mac_address:
                continue
            device_mac = re.sub(r'[^0-9A-Fa-f]', '', device.mac_address).upper()
            if device_mac == mac_clean:
                return device
        return None
    
    def find_device_by_name(self, name: str, session=None) -> Optional[Device]:
        """通过设备名查找设备"""
        if not name:
            return None
        if session is None:
            session = db.session
        return session.query(Device).filter(Device.name.ilike(f'%{name}%')).first()
    
    def find_interface_by_name(self, device_id: int, name: str, session=None) -> Optional[Interface]:
        """通过设备ID和端口名查找接口"""
        if not name:
            return None
        if session is None:
            session = db.session
        return session.query(Interface).filter(
            and_(Interface.device_id == device_id, Interface.name == name)
        ).first()
    
    def find_interface_by_mac(self, device_id: int, mac: str, session=None) -> Optional[Interface]:
        """通过设备ID和MAC地址查找接口"""
        if not mac:
            return None
        mac_clean = re.sub(r'[^0-9A-Fa-f]', '', mac).upper()
        
        if session is None:
            session = db.session
        
        interfaces = session.query(Interface).filter(
            and_(Interface.device_id == device_id, Interface.mac_address.isnot(None))
        ).all()
        
        for interface in interfaces:
            if not interface.mac_address:
                continue
            iface_mac = re.sub(r'[^0-9A-Fa-f]', '', interface.mac_address).upper()
            if iface_mac == mac_clean:
                return interface
        return None
    
    # ==================== LLDP链路验证 ====================
    
    def verify_link_via_lldp(self, source_device: Device, source_port: Interface,
                             target_device: Device, target_port: Interface) -> Tuple[bool, str]:
        """通过LLDP验证链路"""
        if not source_device.management_ip:
            return False, '源设备无管理IP'
        
        neighbors = self.get_lldp_neighbors(
            source_device.management_ip,
            source_port.name,
            community=source_device.snmp_community or 'public'
        )
        
        if not neighbors:
            return False, f'端口 {source_port.name} 无LLDP邻居'
        
        # 准备目标匹配ID列表
        target_ids = []
        
        # 设备MAC地址
        if target_device.mac_address:
            target_ids.append(re.sub(r'[^0-9A-Fa-f]', '', target_device.mac_address).upper())
        
        # 端口MAC地址
        if target_port.mac_address:
            target_ids.append(re.sub(r'[^0-9A-Fa-f]', '', target_port.mac_address).upper())
        
        # 设备名称（多种格式）
        if target_device.name:
            target_ids.append(target_device.name.lower())
            target_ids.append(target_device.name.strip())
        
        # 端口名称（多种格式）
        if target_port.name:
            target_ids.append(target_port.name.lower())
            target_ids.append(target_port.name.strip())
            # 去掉可能的前缀
            port_short = re.sub(r'^(gigabitethernet|ge|ten-gigabitethernet|tengigabitethernet|ethernet|eth)', '', target_port.name.lower())
            target_ids.append(port_short)
        
        print(f"  [DEBUG] 目标匹配ID列表: {target_ids}")
        
        for neighbor in neighbors:
            # 获取邻居信息并清理
            chassis_id = neighbor.get('chassis_id', '')
            remote_port_id = neighbor.get('remote_port_id', '')
            remote_system_name = neighbor.get('remote_system_name', '')
            
            # 去除引号和多余空格
            def clean_value(val):
                if not val:
                    return ''
                val = val.strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                if val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                return val.strip()
            
            chassis_clean = clean_value(chassis_id)
            remote_port_clean = clean_value(remote_port_id)
            remote_name_clean = clean_value(remote_system_name)
            
            print(f"  [DEBUG] 邻居: chassis={chassis_clean}, port={remote_port_clean}, name={remote_name_clean}")
            
            # 检查Chassis ID是否匹配
            for target_id in target_ids:
                if chassis_clean and target_id:
                    # 清理后比较（MAC地址去除特殊字符）
                    chassis_clean_mac = re.sub(r'[^0-9A-Fa-f]', '', chassis_clean).upper()
                    target_clean = re.sub(r'[^0-9A-Fa-f]', '', target_id).upper()
                    if chassis_clean_mac == target_clean:
                        return True, f'LLDP验证成功: {remote_name_clean}'
            
            # 检查系统名称是否匹配
            for target_id in target_ids:
                if remote_name_clean and target_id:
                    if remote_name_clean.lower() == target_id.lower():
                        return True, f'LLDP验证成功: {remote_name_clean}'
                    # 检查是否包含
                    if remote_name_clean.lower() in target_id.lower() or target_id.lower() in remote_name_clean.lower():
                        return True, f'LLDP验证成功: {remote_name_clean}'
            
            # 检查远程端口ID是否匹配目标端口名称
            for target_id in target_ids:
                if remote_port_clean and target_id:
                    # 清理端口名称（去掉前缀）
                    remote_port_clean_short = re.sub(r'^(gigabitethernet|ge|ten-gigabitethernet|tengigabitethernet|ethernet|eth)', '', remote_port_clean.lower())
                    target_clean_short = re.sub(r'^(gigabitethernet|ge|ten-gigabitethernet|tengigabitethernet|ethernet|eth)', '', target_id.lower())
                    
                    if remote_port_clean.lower() == target_id.lower():
                        return True, f'LLDP验证成功: {remote_name_clean}'
                    if remote_port_clean_short == target_clean_short:
                        return True, f'LLDP验证成功: {remote_name_clean}'
                    # 检查端口编号匹配 (如 1/0/3)
                    port_num_match = re.search(r'(\d+/\d+/\d+)', remote_port_clean)
                    target_num_match = re.search(r'(\d+/\d+/\d+)', target_id)
                    if port_num_match and target_num_match:
                        if port_num_match.group(1) == target_num_match.group(1):
                            return True, f'LLDP验证成功: {remote_name_clean}'
        
        return False, f'LLDP邻居不匹配'
    
    # ==================== 核心链路检测 ====================
    
    def check_single_link(self, connection_id: int, session) -> Dict:
        """检测单条链路（在独立会话中执行）"""
        start_time = time.time()
        result = {
            'connection_id': connection_id,
            'status': 'unknown',
            'reason': '',
            'source_status': 'unknown',
            'target_status': 'unknown',
            'elapsed': 0
        }
        
        try:
            print(f"\n{'='*60}")
            print(f"检测链路 ID: {connection_id}")
            
            # 在独立会话中查询连接及其关联对象
            connection = session.get(ConnectionPath, connection_id)
            if not connection:
                result['status'] = 'down'
                result['reason'] = '链路不存在'
                result['elapsed'] = time.time() - start_time
                return result
            
            source_device = connection.source_device
            target_device = connection.target_device
            source_port = connection.source_interface
            target_port = connection.target_interface

            # AP / 边缘设备链路：目标端通常无 SNMP 或无管理 IP，
            # 不能再用"双向 SNMP 端口轮询"判定，否则会误判为 down。
            is_ap_link = (connection.link_role == 'edge_ap') or \
                         (target_device is not None and target_device.device_type == 'ap')

            print(f"源设备: {source_device.name} (ID: {source_device.id}, IP: {source_device.management_ip})")
            print(f"目标设备: {target_device.name} (ID: {target_device.id}, IP: {target_device.management_ip})")
            print(f"源端口: {source_port.name} (ID: {source_port.id})")
            print(f"目标端口: {target_port.name} (ID: {target_port.id})")
            print(f"链路角色: {'edge_ap(AP/边缘)' if is_ap_link else 'normal'}")

            # ===== 快照后立即释放数据库连接：Ping/SNMP 网络 I/O 阶段零连接占用 =====
            # 对象已 detach，但已加载的列属性仍可读取；ifindex 缓存与状态回写
            # 由外层 _check_link_in_thread 在检测完成后用新事务落库，
            # 避免 20 个并发线程在慢速网络期间把 QueuePool 占满导致其它任务超时。
            try:
                session.close()
            except Exception:
                pass

            if not source_device or not target_device:
                result['status'] = 'down'
                result['reason'] = '源设备或目标设备不存在'
                result['elapsed'] = time.time() - start_time
                return result

            if not source_port or not target_port:
                result['status'] = 'down'
                result['reason'] = '源端口或目标端口不存在'
                result['elapsed'] = time.time() - start_time
                return result

            if not source_device.management_ip or (not target_device.management_ip and not is_ap_link):
                result['status'] = 'down'
                result['reason'] = '设备IP地址未配置' if not source_device.management_ip else '源设备IP地址未配置'
                result['elapsed'] = time.time() - start_time
                return result

            # 1. Ping检测（AP 链路仅检测源设备，目标 AP 通常不响应 ping / 无管理 IP）
            print(f"\n[Ping检测] 源设备 {source_device.management_ip}...")
            source_online, source_ping_time = self.ping_check(source_device.management_ip)
            print(f"  Ping结果: {'在线' if source_online else '离线'} ({source_ping_time:.2f}ms)")

            if not is_ap_link:
                print(f"[Ping检测] 目标设备 {target_device.management_ip}...")
                target_online, target_ping_time = self.ping_check(target_device.management_ip)
                print(f"  Ping结果: {'在线' if target_online else '离线'} ({target_ping_time:.2f}ms)")

            if not source_online:
                result['status'] = 'down'
                result['reason'] = f'源设备 {source_device.name}({source_device.management_ip}) 掉线'
                result['source_status'] = 'down'
                result['target_status'] = 'unknown'
                result['elapsed'] = time.time() - start_time
                return result

            if not is_ap_link and not target_online:
                result['status'] = 'down'
                result['reason'] = f'目标设备 {target_device.name}({target_device.management_ip}) 掉线'
                result['source_status'] = 'up'
                result['target_status'] = 'down'
                result['elapsed'] = time.time() - start_time
                return result

            # 2. 检查源端口状态
            print(f"\n[源端口检测] {source_device.management_ip} -> {source_port.name}")
            # 优先使用已缓存的 ifindex（由 sync_device_interfaces 写入），避免每次整表 SNMP walk
            source_ifindex = source_port.ifindex
            if not source_ifindex:
                # 缓存未命中，回退到 SNMP walk 查找
                source_ifindex = self.get_interface_ifindex(
                    source_device.management_ip,
                    source_port.name,
                    source_device.snmp_community or 'public'
                )
                if source_ifindex:
                    # 回写由外层统一落库，检测阶段不占连接
                    result['source_ifindex_found'] = source_ifindex

            if source_ifindex is None:
                result['status'] = 'down'
                result['reason'] = f'无法获取源端口 {source_port.name} 的ifindex'
                result['source_status'] = 'unknown'
                result['target_status'] = 'up' if (not is_ap_link) else 'n/a'
                result['elapsed'] = time.time() - start_time
                return result

            print(f"  源端口 ifindex: {source_ifindex}")
            source_status = self.get_port_status(
                source_device.management_ip,
                source_ifindex,
                source_device.snmp_community or 'public'
            )
            print(f"  源端口状态: {source_status} (1=up, 2=down)")

            # ===== AP / 边缘链路：不轮询目标端 SNMP，仅用源端口 up + LLDP 邻居存在判定 =====
            if is_ap_link:
                result['target_status'] = 'n/a'  # AP 侧不轮询
                if source_status == 1:
                    print(f"\n[AP链路判定] 源端口up，进行 LLDP 邻居验证（仅查源设备）...")
                    lldp_verified, lldp_msg = self.verify_link_via_lldp(
                        source_device, source_port, target_device, target_port
                    )
                    if lldp_verified:
                        result['status'] = 'active'
                        result['reason'] = f'AP链路正常(源端口up+LLDP验证): {lldp_msg}'
                    else:
                        result['status'] = 'down'
                        result['reason'] = f'源端口up但LLDP未看到该AP邻居: {lldp_msg}'
                else:
                    result['status'] = 'down'
                    result['reason'] = f'源端口 {source_port.name} 处于down状态'
                result['elapsed'] = time.time() - start_time
                print(f"\n检测完成: {result['status']}")
                print(f"{'='*60}\n")
                return result

            # 3. 检查目标端口状态（非 AP 链路）
            print(f"\n[目标端口检测] {target_device.management_ip} -> {target_port.name}")
            # 优先使用已缓存的 ifindex，避免每次整表 SNMP walk
            target_ifindex = target_port.ifindex
            if not target_ifindex:
                target_ifindex = self.get_interface_ifindex(
                    target_device.management_ip,
                    target_port.name,
                    target_device.snmp_community or 'public'
                )
                if target_ifindex:
                    result['target_ifindex_found'] = target_ifindex

            if target_ifindex is None:
                result['status'] = 'down'
                result['reason'] = f'无法获取目标端口 {target_port.name} 的ifindex'
                result['source_status'] = 'up' if source_status == 1 else 'down'
                result['target_status'] = 'unknown'
                result['elapsed'] = time.time() - start_time
                return result

            print(f"  目标端口 ifindex: {target_ifindex}")
            target_status = self.get_port_status(
                target_device.management_ip,
                target_ifindex,
                target_device.snmp_community or 'public'
            )
            print(f"  目标端口状态: {target_status} (1=up, 2=down)")

            result['source_status'] = 'up' if source_status == 1 else 'down'
            result['target_status'] = 'up' if target_status == 1 else 'down'
            # 4. 判断链路状态
            print(f"\n[链路判断] 源状态: {result['source_status']}, 目标状态: {result['target_status']}")
            
            if source_status == 1 and target_status == 1:
                print("  两端端口都up，进行LLDP验证...")
                lldp_verified, lldp_msg = self.verify_link_via_lldp(
                    source_device, source_port, target_device, target_port
                )
                
                if lldp_verified:
                    result['status'] = 'active'
                    result['reason'] = f'链路正常: {lldp_msg}'
                    print(f"  LLDP验证成功: {lldp_msg}")
                else:
                    result['status'] = 'down'
                    result['reason'] = f'端口up但LLDP验证失败: {lldp_msg}'
                    print(f"  LLDP验证失败: {lldp_msg}")
            else:
                result['status'] = 'down'
                if source_status != 1 and target_status != 1:
                    result['reason'] = '两端端口均为down状态'
                elif source_status != 1:
                    result['reason'] = f'源端口 {source_port.name} 处于down状态'
                else:
                    result['reason'] = f'目标端口 {target_port.name} 处于down状态'
                print(f"  链路down: {result['reason']}")
            
        except Exception as e:
            result['status'] = 'down'
            result['reason'] = f'检测异常: {str(e)}'
            result['elapsed'] = time.time() - start_time
            import traceback
            traceback.print_exc()
            return result
        
        result['elapsed'] = time.time() - start_time
        print(f"\n检测完成: {result['status']}")
        print(f"{'='*60}\n")
        return result
    
    # ==================== 数据库更新 ====================
    
    def update_connection_status(self, connection_id: int, result: Dict, session):
        """更新连接状态到数据库"""
        try:
            connection = session.get(ConnectionPath, connection_id)
            if not connection:
                print(f"链路 {connection_id} 未找到")
                return
            
            old_status = connection.link_status or 'unknown'
            new_status = result['status']
            
            if old_status != new_status:
                connection.link_status = new_status
                connection.updated_at = datetime.now()
                
                source_device = session.get(Device, connection.source_device_id)
                target_device = session.get(Device, connection.target_device_id)
                device_ip = source_device.management_ip if source_device else ''
                
                log = DeviceMonitorLog(
                    device_id=connection.source_device_id,
                    device_ip=device_ip,
                    old_status=old_status,
                    new_status=new_status,
                    error_message=result.get('reason', ''),
                    monitor_type='link_monitor',
                    is_online=(new_status == 'active')
                )
                session.add(log)
                
                # 告警处理：链路断开创建/更新告警，链路恢复关闭告警
                alert_status = None
                if new_status == 'down':
                    self._create_alert_in_session(session, connection, result)
                    alert_status = 'active'
                elif new_status == 'active' and old_status == 'down':
                    self._clear_alert_in_session(session, connection)
                    alert_status = 'resolved'
                
                # 链路状态改变：告警信息写入系统日志
                src_name = source_device.name if source_device else str(connection.source_device_id)
                dst_name = target_device.name if target_device else str(connection.target_device_id)
                reason = result.get('reason', '')
                alert_title = (
                    f'链路断开: {connection.source_port} -> {connection.target_port}'
                    if new_status == 'down'
                    else f'链路恢复: {connection.source_port} -> {connection.target_port}'
                )
                session.add(SystemLog(
                    timestamp=datetime.utcnow(),
                    level='warning' if new_status == 'down' else 'info',
                    module='link_monitor',
                    source=f'link:{connection.id}',
                    message=(
                        f'链路 {src_name}:{connection.source_port} -> '
                        f'{dst_name}:{connection.target_port} '
                        f'状态变化: {old_status} -> {new_status}'
                        + (f'，原因: {reason}' if reason else '')
                    ),
                    details=json.dumps({
                        'alert_title': alert_title,
                        'severity': 'critical' if new_status == 'down' else 'info',
                        'alert_status': alert_status,
                        'reason': reason,
                        'source_port': connection.source_port,
                        'target_port': connection.target_port,
                    }, ensure_ascii=False),
                ))
                
                session.commit()
                print(f"链路 {connection_id} 状态已更新: {old_status} -> {new_status}")
            else:
                connection.updated_at = datetime.now()
                session.commit()
                
        except Exception as e:
            session.rollback()
            print(f"update_connection_status 异常: {e}")
            raise

    def _update_ifindex_cache(self, connection_id: int, result: Dict, session):
        """把检测阶段 SNMP walk 得到的 ifindex 写回接口缓存（短事务，不占连接池）。"""
        try:
            connection = session.get(ConnectionPath, connection_id)
            if not connection:
                return
            changed = False
            if result.get('source_ifindex_found'):
                port = connection.source_interface
                if port and port.ifindex != result['source_ifindex_found']:
                    port.ifindex = result['source_ifindex_found']
                    changed = True
            if result.get('target_ifindex_found'):
                port = connection.target_interface
                if port and port.ifindex != result['target_ifindex_found']:
                    port.ifindex = result['target_ifindex_found']
                    changed = True
            if changed:
                session.commit()
                print(f"链路 {connection_id} ifindex 缓存已更新")
        except Exception as e:
            session.rollback()
            print(f"_update_ifindex_cache 异常: {e}")
    
    def _create_alert_in_session(self, session, connection: ConnectionPath, result: Dict):
        """在会话中创建告警"""
        try:
            source_device = session.get(Device, connection.source_device_id)
            target_device = session.get(Device, connection.target_device_id)
            
            if not source_device:
                return
            
            existing = session.query(AlertEvent).filter(
                and_(
                    AlertEvent.device_id == connection.source_device_id,
                    AlertEvent.title.like(f'%链路断开%{connection.source_port}%'),
                    AlertEvent.status == 'active'
                )
            ).first()
            
            if existing:
                existing.last_occurred = datetime.now()
                existing.occurrence_count += 1
                existing.message = f'链路 {source_device.name}:{connection.source_port} -> {target_device.name}:{connection.target_port} 断开'
                return

            alert = AlertEvent(
                device_id=connection.source_device_id,
                rule_id=None,
                title=f'链路断开: {connection.source_port} -> {connection.target_port}',
                message=f'链路 {source_device.name}:{connection.source_port} -> {target_device.name}:{connection.target_port} 断开，原因: {result.get("reason", "")}',
                severity='critical',
                status='active',
                first_occurred=datetime.now(),
                last_occurred=datetime.now(),
                occurrence_count=1,
                notified=False
            )
            session.add(alert)
            # 事件归一化/关联规则引擎：告警落库前应用抑制与归一化
            try:
                from utils.event_correlation import process_alert_correlation
                session.flush()
                if self.app:
                    with self.app.app_context():
                        process_alert_correlation(session, alert)
                else:
                    process_alert_correlation(session, alert)
            except Exception as ce:
                print(f"事件关联规则应用失败(忽略): {ce}")
        except Exception as e:
            print(f"_create_alert_in_session 异常: {e}")
            raise
    
    def _clear_alert_in_session(self, session, connection: ConnectionPath):
        """在会话中清除告警"""
        try:
            alerts = session.query(AlertEvent).filter(
                and_(
                    AlertEvent.device_id == connection.source_device_id,
                    AlertEvent.title.like(f'%链路断开%{connection.source_port}%'),
                    AlertEvent.status == 'active'
                )
            ).all()
            
            for alert in alerts:
                alert.status = 'resolved'
                alert.resolved_at = datetime.now()
                alert.resolved_note = '链路已恢复'
        except Exception as e:
            print(f"_clear_alert_in_session 异常: {e}")
            raise
    
    def _get_session(self):
        """获取数据库会话"""
        if self.Session:
            return self.Session()
        return db.session
    
    # ==================== 批量链路检测 ====================
    
    def check_all_links(self, connection_ids: Optional[List[int]] = None) -> List[Dict]:
        """批量检测所有链路"""
        results = []
        
        try:
            query = ConnectionPath.query
            if connection_ids:
                query = query.filter(ConnectionPath.id.in_(connection_ids))
            
            connections = query.filter(
                ConnectionPath.source_interface_id.isnot(None),
                ConnectionPath.target_interface_id.isnot(None)
            ).all()
            
            print(f"查询到 {len(connections)} 条有效链路需要检测")
            if not connections:
                return results
            
            conn_ids = [c.id for c in connections]
            
            futures = {}
            for conn_id in conn_ids:
                future = self.pool.submit(self._check_link_in_thread, conn_id)
                futures[future] = conn_id
            
            for future in as_completed(futures, timeout=120):
                conn_id = futures[future]
                try:
                    result = future.result(timeout=30)
                    results.append(result)
                    print(f"链路 {conn_id} 检测结果: {result['status']}, 原因: {result.get('reason', 'N/A')}")
                except Exception as e:
                    error_msg = f'检测异常: {str(e)}'
                    print(f"链路 {conn_id} {error_msg}")
                    results.append({
                        'connection_id': conn_id,
                        'status': 'down',
                        'reason': error_msg,
                        'source_status': 'unknown',
                        'target_status': 'unknown',
                        'elapsed': 0
                    })
            
        except Exception as e:
            print(f"check_all_links 整体异常: {e}")
            import traceback
            traceback.print_exc()
            raise
        
        return results
    
    def _check_link_in_thread(self, conn_id: int) -> Dict:
        """在线程中检测单条链路（使用独立会话）"""
        session = None
        try:
            if self.Session:
                session = self.Session()
            else:
                session = db.session
            
            result = self.check_single_link(conn_id, session)

            if result.get('source_ifindex_found') or result.get('target_ifindex_found'):
                self._update_ifindex_cache(conn_id, result, session)

            self.update_connection_status(conn_id, result, session)

            return result
        except Exception as e:
            if session:
                session.rollback()
            print(f"_check_link_in_thread 异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                'connection_id': conn_id,
                'status': 'down',
                'reason': f'检测异常: {str(e)}',
                'source_status': 'unknown',
                'target_status': 'unknown',
                'elapsed': 0
            }
        finally:
            if session:
                if self.Session:
                    session.close()
                else:
                    db.session.remove()
    
    # ==================== LLDP自动发现 ====================

    @staticmethod
    def _looks_like_ap(neighbor: Dict, target_device=None) -> bool:
        """判断 LLDP 邻居是否为 AP / 无线边缘设备。

        优先依据资产库中已登记的 device_type=='ap'；
        否则根据 LLDP 上报的 sysName / sysDesc 关键词猜测（用于尚未入库的未知 AP）。
        """
        if target_device is not None and getattr(target_device, 'device_type', None) == 'ap':
            return True
        text = ' '.join([
            str(neighbor.get('remote_system_name', '') or ''),
            str(neighbor.get('remote_sys_desc', '') or ''),
        ]).lower()
        return any(kw in text for kw in AP_KEYWORDS)

    def discover_links_via_lldp(self, device_ids: Optional[List[int]] = None) -> Dict:
        """通过LLDP自动发现链路"""
        result = {
            'total_devices': 0,
            'discovered_links': 0,
            'new_links': 0,
            'updated_links': 0,
            'errors': 0,
            'unknown_neighbors': 0,
            'details': []
        }
        
        session = self._get_session()
        
        try:
            query = session.query(Device).filter(Device.management_ip.isnot(None))
            if device_ids:
                query = query.filter(Device.id.in_(device_ids))
            
            devices = query.all()
            result['total_devices'] = len(devices)
            
            for device in devices:
                if not device.management_ip:
                    continue
                
                try:
                    neighbors = self.get_lldp_neighbors(
                        device.management_ip,
                        community=device.snmp_community or 'public'
                    )
                    
                    for neighbor in neighbors:
                        target_device = self.find_device_by_mac(neighbor.get('chassis_id', ''), session)
                        if not target_device and neighbor.get('remote_system_name'):
                            target_device = self.find_device_by_name(neighbor['remote_system_name'], session)
                        
                        if not target_device:
                            # 对端不在资产库：不创建 ConnectionPath（避免污染 CMDB），
                            # 但记录为未知邻居，便于发现"交换机口下挂了未登记设备（如 AP）"。
                            guessed_ap = self._looks_like_ap(neighbor)
                            result['unknown_neighbors'] += 1
                            result['details'].append({
                                'source': f"{device.name}:{neighbor.get('local_port', '?')}",
                                'target': neighbor.get('remote_system_name') or neighbor.get('chassis_id') or 'unknown',
                                'status': 'unmanaged',
                                'guessed_ap': guessed_ap
                            })
                            continue
                        
                        source_port = self.find_interface_by_name(device.id, neighbor['local_port'], session)
                        if not source_port:
                            continue
                        
                        target_port = self.find_interface_by_mac(
                            target_device.id,
                            neighbor.get('remote_port_id', ''),
                            session
                        )
                        if not target_port and neighbor.get('remote_port_id'):
                            target_port = self.find_interface_by_name(
                                target_device.id,
                                neighbor['remote_port_id'],
                                session
                            )
                        
                        if not target_port:
                            continue

                        # ========== 双向归一化 + 设备对去重 ==========
                        # 物理链路 A--B 只应存一条，不管扫描方向是谁→谁
                        # 必须先归一化（使小 ID 为 source），再做去重查询，
                        # 否则反向扫描会创建重复连接
                        if device.id > target_device.id:
                            # 反向：交换源/目标
                            real_src_dev = target_device
                            real_src_port_obj = target_port
                            real_tgt_dev = device
                            real_tgt_port_obj = source_port
                        else:
                            real_src_dev = device
                            real_src_port_obj = source_port
                            real_tgt_dev = target_device
                            real_tgt_port_obj = target_port

                        # 双方向去重：精确匹配（按归一化后的端点）
                        existing = session.query(ConnectionPath).filter(
                            db.or_(
                                db.and_(
                                    ConnectionPath.source_device_id == real_src_dev.id,
                                    ConnectionPath.source_interface_id == real_src_port_obj.id,
                                    ConnectionPath.target_device_id == real_tgt_dev.id,
                                    ConnectionPath.target_interface_id == real_tgt_port_obj.id
                                ),
                                # 反向：原已存 (B,A)，新归一化后也是 (A,B)
                                db.and_(
                                    ConnectionPath.source_device_id == real_tgt_dev.id,
                                    ConnectionPath.source_interface_id == real_tgt_port_obj.id,
                                    ConnectionPath.target_device_id == real_src_dev.id,
                                    ConnectionPath.target_interface_id == real_src_port_obj.id
                                ),
                            )
                        ).first()

                        if existing:
                            existing.discovery_time = datetime.now()
                            existing.last_seen = datetime.now()  # 刷新"最近确认在线"时间，供老化判断
                            existing.discovery_protocol = 'LLDP'
                            existing.link_status = 'active'
                            existing.confidence = 100
                            existing.auto_discovered = True
                            if self._looks_like_ap(neighbor, target_device):
                                existing.link_role = 'edge_ap'
                                existing.neighbor_managed = True
                                # 同步把受管 AP 资产归类为 ap（仅当未明确设置时，避免覆盖人工类型）
                                if target_device.device_type in (None, '', 'unknown', 'other'):
                                    target_device.device_type = 'ap'
                            result['updated_links'] += 1
                        else:
                            is_ap = self._looks_like_ap(neighbor, target_device)
                            if is_ap and target_device.device_type in (None, '', 'unknown', 'other'):
                                target_device.device_type = 'ap'
                            connection = ConnectionPath(
                                source_device_id=real_src_dev.id,
                                source_interface_id=real_src_port_obj.id,
                                target_device_id=real_tgt_dev.id,
                                target_interface_id=real_tgt_port_obj.id,
                                source_port=real_src_port_obj.name,
                                target_port=real_tgt_port_obj.name,
                                connection_type='physical',
                                link_status='active',
                                discovered_by='LLDP',
                                discovery_protocol='LLDP',
                                discovery_time=datetime.now(),
                                last_seen=datetime.now(),
                                auto_discovered=True,
                                neighbor_managed=True,
                                link_role='edge_ap' if is_ap else 'normal',
                                confidence=100
                            )
                            session.add(connection)
                            session.flush()  # 让本批后续查询可见
                            result['new_links'] += 1

                        result['discovered_links'] += 1
                        result['details'].append({
                            'source': f"{real_src_dev.name}:{real_src_port_obj.name}",
                            'target': f"{real_tgt_dev.name}:{real_tgt_port_obj.name}",
                            'status': 'new' if not existing else 'updated'
                        })

                except Exception as e:
                    result['errors'] += 1
                    continue
            
            session.commit()
        except Exception as e:
            session.rollback()
            print(f"discover_links_via_lldp 异常: {e}")
        finally:
            if self.Session:
                session.close()
            else:
                db.session.remove()
        
        return result
    
    # ==================== 拓扑同步 ====================
    
    def sync_topology(self):
        """同步所有设备拓扑"""
        discovery_result = self.discover_links_via_lldp()
        link_results = self.check_all_links()
        
        active_count = sum(1 for r in link_results if r['status'] == 'active')
        down_count = sum(1 for r in link_results if r['status'] == 'down')
        
        return {
            'discovery': discovery_result,
            'link_check': {
                'total': len(link_results),
                'active': active_count,
                'down': down_count,
                'details': link_results
            }
        }


    # ==================== 僵尸链路老化清理 ====================

    def prune_stale_links(self, ttl_hours: Optional[int] = None) -> Dict:
        """清理自动发现的僵尸链路。

        自动发现的链路（auto_discovered=True）若超过 TTL 未再被 LLDP 发现确认
        （last_seen 过期），说明对端可能已挪位/下线，将其软标记为 'stale'，
        不硬删除以保留审计。TTL 默认 72 小时，可由 MonitorSetting
        'link_stale_ttl_hours' 覆盖。
        """
        from models.models import MonitorSetting

        if ttl_hours is None:
            try:
                setting = MonitorSetting.query.filter_by(
                    setting_key='link_stale_ttl_hours'
                ).first()
                ttl_hours = int(setting.get_value()) if setting else 72
            except Exception:
                ttl_hours = 72

        threshold = datetime.now() - timedelta(hours=ttl_hours)

        stale = ConnectionPath.query.filter(
            ConnectionPath.auto_discovered == True,
            ConnectionPath.last_seen.isnot(None),
            ConnectionPath.last_seen < threshold,
            ConnectionPath.link_status != 'stale'
        ).all()

        marked = 0
        for c in stale:
            c.link_status = 'stale'
            marked += 1

        if marked:
            db.session.commit()

        return {
            'marked_stale': marked,
            'ttl_hours': ttl_hours,
            'threshold': threshold.isoformat() if hasattr(threshold, 'isoformat') else str(threshold)
        }


# ==================== 任务入口函数 ====================

def run_link_monitor(app: Flask):
    """运行链路监控任务"""
    with app.app_context():
        try:
            print(f"[{datetime.now()}] 开始链路监控任务")
            # 复用 init_link_monitor 已创建的实例，避免每次调度新建线程池导致线程泄漏
            monitor = getattr(app, 'link_monitor', None) or LinkMonitor(app)
            
            total_links = ConnectionPath.query.count()
            print(f"[{datetime.now()}] 共有 {total_links} 条链路需要监控")
            
            result = monitor.check_all_links()
            
            active_count = sum(1 for r in result if r['status'] == 'active')
            down_count = sum(1 for r in result if r['status'] == 'down')
            print(f"[{datetime.now()}] 检测完成: 活动={active_count}, 断开={down_count}")
            
            for r in result:
                if r['status'] == 'down':
                    print(f"[{datetime.now()}] 断开链路: ID={r['connection_id']}, 原因={r.get('reason', '未知')}")
            
            return result
        except Exception as e:
            print(f"[{datetime.now()}] 链路监控任务异常: {e}")
            import traceback
            traceback.print_exc()
            raise


def discover_topology(app: Flask):
    """运行拓扑发现任务"""
    with app.app_context():
        monitor = LinkMonitor(app)
        result = monitor.discover_links_via_lldp()
        return result


def prune_stale_links_task(app: Flask):
    """运行僵尸链路老化清理任务（定时入口）"""
    with app.app_context():
        try:
            print(f"[{datetime.now()}] 开始僵尸链路老化清理")
            monitor = LinkMonitor(app)
            result = monitor.prune_stale_links()
            print(f"[{datetime.now()}] 老化清理完成: {result}")
            return result
        except Exception as e:
            print(f"[{datetime.now()}] 僵尸链路清理异常: {e}")
            import traceback
            traceback.print_exc()
            raise


def sync_topology_task(app: Flask):
    """运行完整拓扑同步任务"""
    with app.app_context():
        monitor = LinkMonitor(app)
        result = monitor.sync_topology()
        return result


def init_link_monitor(app: Flask):
    """初始化链路监控器"""
    monitor = LinkMonitor(app)
    app.link_monitor = monitor
    return monitor
