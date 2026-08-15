# services/device_service.py
"""
统一的设备管理服务 - 所有导入/发现功能共用
确保设备去重逻辑一致，支持信息互相补充
"""
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timezone
from sqlalchemy import or_
from extensions import db
from models.models import Device
import re


def normalize_mac(mac: str) -> str:
    """
    标准化MAC地址为12位十六进制字符串（无分隔符小写）
    支持格式: 00:e0:4c:3e:0c:70, 00e0-4c3e-0c70, 8C E6 66 67 34 25, 00e04c3e0c70
    """
    if not mac:
        return ''
    # 移除所有分隔符和空格，只保留十六进制字符
    hex_chars = ''.join(c for c in str(mac).lower() if c in '0123456789abcdef')
    if not hex_chars:
        return ''
    if len(hex_chars) < 12:
        hex_chars = hex_chars.zfill(12)
    if len(hex_chars) > 12:
        hex_chars = hex_chars[:12]
    return hex_chars


def format_mac_display(mac: str) -> str:
    """将标准化MAC格式化为显示格式 (00:11:22:33:44:55)"""
    norm = normalize_mac(mac)
    if len(norm) == 12:
        return ':'.join(norm[i:i+2] for i in range(0, 12, 2))
    return mac


def find_device(
    ip: Optional[str] = None,
    mac: Optional[str] = None,
    name: Optional[str] = None,
    hostname: Optional[str] = None,
    create_if_not_found: bool = False,
    device_type: str = 'unknown',
    **defaults
) -> Tuple[Optional[Device], str]:
    """
    统一的设备查找/创建函数
    
    优先级：
    1. 通过 management_ip 查找
    2. 通过 ip_address 查找
    3. 通过 MAC 地址查找（标准化匹配）
    4. 通过设备名称查找
    5. 通过 hostname 查找
    
    返回: (device, action) 其中 action 为 'found', 'updated', 'created'
    """
    action = 'not_found'
    device = None
    
    # 标准化MAC
    mac_norm = normalize_mac(mac) if mac else ''
    
    # ========== 1. 通过IP查找 ==========
    if ip:
        device = Device.query.filter(
            or_(
                Device.management_ip == ip,
                Device.ip_address == ip
            )
        ).first()
        if device:
            action = 'found'
            # 如果设备没有MAC但有传入MAC，补充
            if mac_norm and not normalize_mac(device.mac_address or ''):
                device.mac_address = format_mac_display(mac_norm)
                action = 'updated'
            
            # 如果设备名称为空或为'unknown'，尝试更新
            if name and (not device.name or device.name == 'unknown' or device.name.startswith('Device-')):
                device.name = name
                action = 'updated'
            
            if action == 'updated':
                device.updated_at = datetime.now(timezone.utc)
                db.session.commit()
            
            return device, action
    
    # ========== 2. 通过MAC查找 ==========
    if mac_norm:
        # 查询所有设备，在Python中做标准化匹配
        all_devices = Device.query.all()
        for dev in all_devices:
            dev_mac_norm = normalize_mac(dev.mac_address or '')
            if dev_mac_norm == mac_norm:
                device = dev
                action = 'found'
                
                # 如果设备没有IP但有传入IP，补充
                if ip and not device.management_ip and not device.ip_address:
                    device.management_ip = ip
                    device.ip_address = ip
                    action = 'updated'
                
                # 如果设备名称不匹配，更新
                if name and (device.name == 'unknown' or device.name.startswith('Device-')):
                    device.name = name
                    action = 'updated'
                
                if action == 'updated':
                    device.updated_at = datetime.now(timezone.utc)
                    db.session.commit()
                
                return device, action
    
    # ========== 3. 通过设备名称查找 ==========
    if name and name != 'unknown' and not name.startswith('Device-'):
        device = Device.query.filter(Device.name == name).first()
        if device:
            action = 'found'
            # 补充IP
            if ip and not device.management_ip and not device.ip_address:
                device.management_ip = ip
                device.ip_address = ip
                action = 'updated'
            # 补充MAC
            if mac_norm and not normalize_mac(device.mac_address or ''):
                device.mac_address = format_mac_display(mac_norm)
                action = 'updated'
            
            if action == 'updated':
                device.updated_at = datetime.now(timezone.utc)
                db.session.commit()
            
            return device, action
    
    # ========== 4. 创建新设备 ==========
    if create_if_not_found:
        # 生成设备名称
        if name and name != 'unknown' and not name.startswith('Device-'):
            dev_name = name
        elif hostname and hostname != 'unknown':
            dev_name = hostname
        elif ip:
            dev_name = f"Device-{ip}"
        elif mac_norm:
            dev_name = f"Device-{mac_norm[:12].upper()}"
        else:
            dev_name = f"Device-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        
        # 确保名称唯一
        existing = Device.query.filter(Device.name == dev_name).first()
        if existing:
            counter = 1
            while True:
                new_name = f"{dev_name}_{counter}"
                if not Device.query.filter(Device.name == new_name).first():
                    dev_name = new_name
                    break
                counter += 1
        
        device = Device(
            name=dev_name,
            management_ip=ip if ip else None,
            ip_address=ip if ip else None,
            mac_address=format_mac_display(mac_norm) if mac_norm else None,
            device_type=device_type,
            status='unknown',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        # 设置额外字段
        for key, value in defaults.items():
            if hasattr(device, key) and key not in ['id', 'created_at', 'updated_at']:
                setattr(device, key, value)
        
        db.session.add(device)
        db.session.flush()
        action = 'created'
    
    return device, action


def find_or_create_device(
    ip: Optional[str] = None,
    mac: Optional[str] = None,
    name: Optional[str] = None,
    hostname: Optional[str] = None,
    device_type: str = 'unknown',
    **defaults
) -> Device:
    """查找或创建设备（自动创建）"""
    device, _ = find_device(
        ip=ip,
        mac=mac,
        name=name,
        hostname=hostname,
        create_if_not_found=True,
        device_type=device_type,
        **defaults
    )
    return device


def find_device_by_any(
    ip: Optional[str] = None,
    mac: Optional[str] = None,
    name: Optional[str] = None,
    hostname: Optional[str] = None
) -> Optional[Device]:
    """仅查找设备，不创建"""
    device, _ = find_device(
        ip=ip,
        mac=mac,
        name=name,
        hostname=hostname,
        create_if_not_found=False
    )
    return device


def merge_duplicate_devices() -> int:
    """
    合并重复设备：检测具有相同IP或MAC的设备，合并信息
    返回合并的设备数量
    """
    merged_count = 0
    
    # 1. 查找相同IP的设备（保留第一个，合并其他）
    ip_groups = {}
    devices = Device.query.all()
    
    for device in devices:
        ip = device.management_ip or device.ip_address
        if ip:
            if ip not in ip_groups:
                ip_groups[ip] = []
            ip_groups[ip].append(device)
    
    for ip, dev_list in ip_groups.items():
        if len(dev_list) > 1:
            # 保留第一个设备，合并其他设备的信息
            primary = dev_list[0]
            for secondary in dev_list[1:]:
                # 合并MAC
                if not primary.mac_address and secondary.mac_address:
                    primary.mac_address = secondary.mac_address
                # 合并名称
                if primary.name == 'unknown' or primary.name.startswith('Device-'):
                    if secondary.name and not secondary.name.startswith('Device-'):
                        primary.name = secondary.name
                # 合并其他信息
                if not primary.device_type or primary.device_type == 'unknown':
                    if secondary.device_type and secondary.device_type != 'unknown':
                        primary.device_type = secondary.device_type
                if not primary.brand and secondary.brand:
                    primary.brand = secondary.brand
                if not primary.model and secondary.model:
                    primary.model = secondary.model
                if not primary.manufacturer and secondary.manufacturer:
                    primary.manufacturer = secondary.manufacturer
                
                primary.updated_at = datetime.now(timezone.utc)
                
                # 删除重复设备
                db.session.delete(secondary)
                merged_count += 1
                print(f"[合并] 合并设备 {secondary.name} -> {primary.name} (IP: {ip})")
    
    # 2. 查找相同MAC的设备
    mac_groups = {}
    devices = Device.query.all()
    
    for device in devices:
        mac_norm = normalize_mac(device.mac_address or '')
        if mac_norm:
            if mac_norm not in mac_groups:
                mac_groups[mac_norm] = []
            mac_groups[mac_norm].append(device)
    
    for mac_norm, dev_list in mac_groups.items():
        if len(dev_list) > 1:
            primary = dev_list[0]
            for secondary in dev_list[1:]:
                # 检查是否已经被标记删除（上一步已删除）
                try:
                    db.session.get(secondary.id)
                except:
                    continue
                
                # 合并IP
                if not primary.management_ip and secondary.management_ip:
                    primary.management_ip = secondary.management_ip
                    primary.ip_address = secondary.ip_address
                # 合并名称
                if primary.name == 'unknown' or primary.name.startswith('Device-'):
                    if secondary.name and not secondary.name.startswith('Device-'):
                        primary.name = secondary.name
                # 合并其他信息
                if not primary.device_type or primary.device_type == 'unknown':
                    if secondary.device_type and secondary.device_type != 'unknown':
                        primary.device_type = secondary.device_type
                if not primary.brand and secondary.brand:
                    primary.brand = secondary.brand
                if not primary.model and secondary.model:
                    primary.model = secondary.model
                if not primary.manufacturer and secondary.manufacturer:
                    primary.manufacturer = secondary.manufacturer
                
                primary.updated_at = datetime.now(timezone.utc)
                
                # 删除重复设备
                db.session.delete(secondary)
                merged_count += 1
                print(f"[合并] 合并设备 {secondary.name} -> {primary.name} (MAC: {mac_norm})")
    
    if merged_count > 0:
        db.session.commit()
        print(f"[合并] 共合并 {merged_count} 个重复设备")
    else:
        print("[合并] 没有发现重复设备")
    
    return merged_count


# def merge_devices_by_ip_mac():
#     """
#     主动合并设备：根据IP和MAC关联，将具有相同IP或MAC的设备合并
#     可在发现任务完成后调用
#     """
#     from models.models import Device
    
#     print("[合并] 开始合并重复设备...")
    
#     # 1. 先按IP合并
#     ip_map = {}
#     for device in Device.query.all():
#         ip = device.management_ip or device.ip_address
#         if ip:
#             if ip not in ip_map:
#                 ip_map[ip] = []
#             ip_map[ip].append(device)
    
#     for ip, devices in ip_map.items():
#         if len(devices) > 1:
#             # 选择信息最完整的作为主设备
#             primary = max(devices, key=lambda d: (
#                 bool(d.name and not d.name.startswith('Device-')),
#                 bool(d.mac_address),
#                 bool(d.manufacturer),
#                 bool(d.model)
#             ))
#             for secondary in devices:
#                 if secondary.id == primary.id:
#                     continue
#                 # 合并信息
#                 if not primary.mac_address and secondary.mac_address:
#                     primary.mac_address = secondary.mac_address
#                 if primary.name == 'unknown' or primary.name.startswith('Device-'):
#                     if secondary.name and not secondary.name.startswith('Device-'):
#                         primary.name = secondary.name
#                 if not primary.device_type or primary.device_type == 'unknown':
#                     if secondary.device_type and secondary.device_type != 'unknown':
#                         primary.device_type = secondary.device_type
#                 # 记录连接迁移（如果有连接指向被删除的设备）
#                 # 这里需要迁移 ConnectionPath
#                 migrate_connections(secondary.id, primary.id)
#                 db.session.delete(secondary)
#                 print(f"[合并] 合并 {secondary.name} -> {primary.name} (IP: {ip})")
    
#     db.session.commit()
    
#     # 2. 再按MAC合并
#     mac_map = {}
#     for device in Device.query.all():
#         mac_norm = normalize_mac(device.mac_address or '')
#         if mac_norm:
#             if mac_norm not in mac_map:
#                 mac_map[mac_norm] = []
#             mac_map[mac_norm].append(device)
    
#     for mac_norm, devices in mac_map.items():
#         if len(devices) > 1:
#             primary = max(devices, key=lambda d: (
#                 bool(d.name and not d.name.startswith('Device-')),
#                 bool(d.management_ip),
#                 bool(d.manufacturer),
#                 bool(d.model)
#             ))
#             for secondary in devices:
#                 if secondary.id == primary.id:
#                     continue
#                 if not primary.management_ip and secondary.management_ip:
#                     primary.management_ip = secondary.management_ip
#                     primary.ip_address = secondary.ip_address
#                 if primary.name == 'unknown' or primary.name.startswith('Device-'):
#                     if secondary.name and not secondary.name.startswith('Device-'):
#                         primary.name = secondary.name
#                 if not primary.device_type or primary.device_type == 'unknown':
#                     if secondary.device_type and secondary.device_type != 'unknown':
#                         primary.device_type = secondary.device_type
#                 migrate_connections(secondary.id, primary.id)
#                 db.session.delete(secondary)
#                 print(f"[合并] 合并 {secondary.name} -> {primary.name} (MAC: {mac_norm})")
    
#     db.session.commit()
#     print("[合并] 合并完成")


# def migrate_connections(old_device_id: int, new_device_id: int):
#     """迁移连接关系"""
#     from models.models import ConnectionPath
    
#     # 更新源设备
#     ConnectionPath.query.filter_by(source_device_id=old_device_id).update({
#         'source_device_id': new_device_id,
#         'updated_at': datetime.now(timezone.utc)
#     })
    
#     # 更新目标设备
#     ConnectionPath.query.filter_by(target_device_id=old_device_id).update({
#         'target_device_id': new_device_id,
#         'updated_at': datetime.now(timezone.utc)
#     })




# services/device_service.py - 添加合并函数

def update_device_info(device: Device, **kwargs) -> bool:
    """
    更新设备信息（仅当字段为空或为默认值时）
    """
    updated = False
    for key, value in kwargs.items():
        if value is None:
            continue
        if hasattr(device, key):
            current = getattr(device, key)
            # 仅当当前值为空或为默认值时更新
            if current is None or current == '' or current == 'unknown':
                setattr(device, key, value)
                updated = True
    
    if updated:
        device.updated_at = datetime.now(timezone.utc)
        db.session.commit()
    
    return updated

def merge_devices_by_ip_mac() -> Dict[str, int]:
    """
    主动合并设备：根据IP和MAC关联，将具有相同IP或MAC的设备合并
    可在发现任务完成后调用
    
    返回: {'merged_count': 合并数量, 'total_devices': 剩余设备数}
    """
    from models.models import Device, ConnectionPath
    import traceback
    
    print("[合并] 开始合并重复设备...")
    merged_count = 0
    
    try:
        # ========== 1. 先按IP合并 ==========
        ip_map = {}
        devices = Device.query.all()
        
        for device in devices:
            ip = device.management_ip or device.ip_address
            if ip:
                if ip not in ip_map:
                    ip_map[ip] = []
                ip_map[ip].append(device)
        
        for ip, dev_list in ip_map.items():
            if len(dev_list) > 1:
                # 选择信息最完整的作为主设备
                primary = max(dev_list, key=lambda d: (
                    bool(d.name and not d.name.startswith('Device-')),
                    bool(d.mac_address),
                    bool(d.manufacturer),
                    bool(d.model),
                    bool(d.brand),
                    d.id  # 如果其他条件相同，保留ID较小的
                ))
                print(f"[合并] IP {ip} 有 {len(dev_list)} 个设备，保留 {primary.name} (ID: {primary.id})")
                
                for secondary in dev_list:
                    if secondary.id == primary.id:
                        continue
                    
                    # 合并信息
                    if not primary.mac_address and secondary.mac_address:
                        primary.mac_address = secondary.mac_address
                        print(f"[合并]   - 补充 MAC: {secondary.mac_address}")
                    
                    if primary.name == 'unknown' or primary.name.startswith('Device-'):
                        if secondary.name and not secondary.name.startswith('Device-') and secondary.name != 'unknown':
                            old_name = primary.name
                            primary.name = secondary.name
                            print(f"[合并]   - 更新名称: {old_name} -> {secondary.name}")
                    
                    if not primary.device_type or primary.device_type == 'unknown':
                        if secondary.device_type and secondary.device_type != 'unknown':
                            primary.device_type = secondary.device_type
                            print(f"[合并]   - 补充类型: {secondary.device_type}")
                    
                    if not primary.manufacturer and secondary.manufacturer:
                        primary.manufacturer = secondary.manufacturer
                        print(f"[合并]   - 补充厂商: {secondary.manufacturer}")
                    
                    if not primary.brand and secondary.brand:
                        primary.brand = secondary.brand
                        print(f"[合并]   - 补充品牌: {secondary.brand}")
                    
                    if not primary.model and secondary.model:
                        primary.model = secondary.model
                        print(f"[合并]   - 补充型号: {secondary.model}")
                    
                    # 合并 SNMP 信息
                    if not primary.snmp_community and secondary.snmp_community:
                        primary.snmp_community = secondary.snmp_community
                    
                    # 迁移连接关系
                    _migrate_connections(secondary.id, primary.id)
                    
                    # 删除重复设备
                    db.session.delete(secondary)
                    merged_count += 1
                    print(f"[合并]   - 删除设备: {secondary.name} (ID: {secondary.id})")
        
        db.session.commit()
        print(f"[合并] 按IP合并完成，共合并 {merged_count} 个设备")
        
        # ========== 2. 再按MAC合并 ==========
        mac_map = {}
        devices = Device.query.all()  # 重新查询
        
        for device in devices:
            mac_norm = normalize_mac(device.mac_address or '')
            if mac_norm:
                if mac_norm not in mac_map:
                    mac_map[mac_norm] = []
                mac_map[mac_norm].append(device)
        
        for mac_norm, dev_list in mac_map.items():
            if len(dev_list) > 1:
                primary = max(dev_list, key=lambda d: (
                    bool(d.name and not d.name.startswith('Device-')),
                    bool(d.management_ip),
                    bool(d.manufacturer),
                    bool(d.model),
                    bool(d.brand),
                    d.id
                ))
                print(f"[合并] MAC {mac_norm} 有 {len(dev_list)} 个设备，保留 {primary.name} (ID: {primary.id})")
                
                for secondary in dev_list:
                    if secondary.id == primary.id:
                        continue
                    
                    # 合并IP
                    if not primary.management_ip and secondary.management_ip:
                        primary.management_ip = secondary.management_ip
                        primary.ip_address = secondary.ip_address
                        print(f"[合并]   - 补充 IP: {secondary.management_ip}")
                    
                    if primary.name == 'unknown' or primary.name.startswith('Device-'):
                        if secondary.name and not secondary.name.startswith('Device-') and secondary.name != 'unknown':
                            old_name = primary.name
                            primary.name = secondary.name
                            print(f"[合并]   - 更新名称: {old_name} -> {secondary.name}")
                    
                    if not primary.device_type or primary.device_type == 'unknown':
                        if secondary.device_type and secondary.device_type != 'unknown':
                            primary.device_type = secondary.device_type
                            print(f"[合并]   - 补充类型: {secondary.device_type}")
                    
                    if not primary.manufacturer and secondary.manufacturer:
                        primary.manufacturer = secondary.manufacturer
                    
                    if not primary.brand and secondary.brand:
                        primary.brand = secondary.brand
                    
                    if not primary.model and secondary.model:
                        primary.model = secondary.model
                    
                    # 迁移连接关系
                    _migrate_connections(secondary.id, primary.id)
                    
                    db.session.delete(secondary)
                    merged_count += 1
                    print(f"[合并]   - 删除设备: {secondary.name} (ID: {secondary.id})")
        
        db.session.commit()
        print(f"[合并] 按MAC合并完成，共合并 {merged_count} 个设备")
        
        total_devices = Device.query.count()
        print(f"[合并] 合并完成，剩余 {total_devices} 个设备")
        
        return {'merged_count': merged_count, 'total_devices': total_devices}
        
    except Exception as e:
        db.session.rollback()
        print(f"[合并] 合并失败: {e}")
        traceback.print_exc()
        return {'merged_count': 0, 'total_devices': Device.query.count(), 'error': str(e)}


def _migrate_connections(old_device_id: int, new_device_id: int):
    """迁移连接关系"""
    from models.models import ConnectionPath
    
    # 更新源设备
    ConnectionPath.query.filter_by(source_device_id=old_device_id).update({
        'source_device_id': new_device_id,
        'updated_at': datetime.now(timezone.utc)
    })
    
    # 更新目标设备
    ConnectionPath.query.filter_by(target_device_id=old_device_id).update({
        'target_device_id': new_device_id,
        'updated_at': datetime.now(timezone.utc)
    })