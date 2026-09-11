from __future__ import annotations
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db  # 关键：从extensions.py导入唯一的db实例
import json
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import relationship
from models._base import utcnow as _utcnow

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='user')
    department = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    @property
    def is_admin(self):
        return self.role == 'admin'
    
    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'

# ==================== 位置/机柜/设备模型 ====================
class Location(db.Model):
    __tablename__ = 'locations'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    description = db.Column(db.Text)
    location_type = db.Column(db.String(50))
    address = db.Column(db.String(256))
    floor = db.Column(db.String(50))
    room_number = db.Column(db.String(50))
    area = db.Column(db.Float)
    capacity = db.Column(db.Integer)
    contact_person = db.Column(db.String(64))
    contact_phone = db.Column(db.String(20))
    contact_email = db.Column(db.String(120))
    contact_department = db.Column(db.String(100))
    power_supply = db.Column(db.Text)
    cooling_system = db.Column(db.Text)
    temperature = db.Column(db.String(50))
    humidity = db.Column(db.String(50))
    access_control = db.Column(db.String(50))
    tags = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    
    def __repr__(self):
        return f'<Location {self.name}>'
    
    def get_used_u_count(self):
        if self.cabinets:
            return sum(cabinet.get_used_u_count() for cabinet in self.cabinets)
        return 0
    
    def cabinet_count(self):
        return len(self.cabinets)

class Cabinet(db.Model):
    __tablename__ = 'cabinets'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False)
    description = db.Column(db.Text)
    height_u = db.Column(db.Integer, default=42)
    power_capacity = db.Column(db.Float)          # 电源容量 (kW)
    # ==========可视机房 ==========
    pos_x = db.Column(db.Float, nullable=True, comment='在机房2D图中的X坐标(百分比)')
    pos_y = db.Column(db.Float, nullable=True, comment='在机房2D图中的Y坐标(百分比)')
    color = db.Column(db.String(20), nullable=True, default='#007bff')
    
    # ==========机柜属性 ==========
    model = db.Column(db.String(64))               # 机柜型号
    manufacturer = db.Column(db.String(64))        # 制造厂商
    width = db.Column(db.Integer)                  # 宽度 (mm)
    depth = db.Column(db.Integer)                  # 深度 (mm)
    weight_capacity = db.Column(db.Integer)        # 承重 (kg)
    power_supply = db.Column(db.Text)              # 电源配置描述
    network_access = db.Column(db.Text)            # 网络接入描述
    cooling_system = db.Column(db.String(128))     # 制冷系统
    tags = db.Column(db.String(256))               # 标签（逗号分隔）
 
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    # 原有关系
    cabinet_id = db.Column(db.Integer, db.ForeignKey('cabinets.id', ondelete='CASCADE'))
    devices = db.relationship('Device', backref='cabinet')


    @property
    def device_count(self):
        if self.devices.__class__.__name__ == 'AppenderQuery':
            return self.devices.count()
        return len(self.devices) if self.devices else 0

    def get_u_availability(self):
        u_slots = {}
        if self.devices:
            for device in self.devices:
                start_u = device.position_u
                height_u = device.height_u
                for i in range(start_u, start_u + height_u):
                    u_slots[i] = {
                        'id': device.id,
                        'name': device.name,
                        'ip_address': device.ip_address,
                        'height_u': device.height_u,
                        'status': device.status
                    }
        total_u = self.height_u or 42
        used_u = len(u_slots)
        remaining_u = total_u - used_u
        usage_percentage = 0
        if total_u > 0:
            usage_percentage = round((used_u / total_u) * 100, 1)
        return {
            'total': total_u,
            'used': used_u,
            'remaining': remaining_u,
            'usage_percentage': usage_percentage,
            'usage_percent': usage_percentage,
            'u_slots': u_slots
        }
    
    def get_used_u_count(self):
        if not self.devices:
            return 0
        return sum((device.height_u or 1) for device in self.devices)

class Device(db.Model):
    __tablename__ = 'devices'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True, index=True)
    device_type = db.Column(db.String(50), default='server')
    brand = db.Column(db.String(64))
    model = db.Column(db.String(64))
    serial_number = db.Column(db.String(64), unique=True, index=True)
    asset_number = db.Column(db.String(64), unique=True, index=True)

    cabinet_id = db.Column(db.Integer, db.ForeignKey('cabinets.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    position_u = db.Column(db.Integer)
    height_u = db.Column(db.Integer, default=1)
    rack_side = db.Column(db.String(10))

    management_ip = db.Column(db.String(45), nullable=True, unique=True)
    ip_address = db.Column(db.String(45))
    mac_address = db.Column(db.String(17))
    # 服务器/宿主机链路核对：BMC 带外管理与虚拟化标识
    bmc_ip = db.Column(db.String(45))            # BMC/带外管理 IP（iLO/iDRAC/XCC 等）
    bmc_mac = db.Column(db.String(17))           # BMC 管理网口 MAC
    virtualization_type = db.Column(db.String(32), default='')  # ''/vmware/kvm/proxmox/hyperv/xen/virtualbox/parallels/other
    is_virtual_host = db.Column(db.Boolean, default=False, index=True)  # 是否虚拟化宿主机

    snmp_community = db.Column(db.String(64))
    snmp_version = db.Column(db.Integer, default=2)
    ssh_username = db.Column(db.String(64))
    ssh_password = db.Column(db.String(255))

    snmp_setting_id = db.Column(db.Integer, db.ForeignKey('snmp_settings.id'), nullable=True)
    credential_id = db.Column(db.Integer, db.ForeignKey('credentials.id'), nullable=True)

    snmp_setting = db.relationship('SNMPSetting', backref='devices', lazy='select')
    credential = db.relationship('Credential', backref='devices', lazy='select')

    status = db.Column(db.String(20), default='unknown', index=True)
    is_decommissioned = db.Column(db.Boolean, default=False, index=True)  # 已下架标记
    # 无线控制器（AC）标记与厂商，供 CAPWAP/AC 发现 AP 使用
    is_wireless_controller = db.Column(db.Boolean, default=False, index=True)
    controller_vendor = db.Column(db.String(32), default='auto')  # auto/h3c/huawei/cisco/aruba/ruijie
    power_status = db.Column(db.String(20))
    cpu_usage = db.Column(db.Float)
    memory_usage = db.Column(db.Float)
    disk_usage = db.Column(db.Float)
    temperature = db.Column(db.Float)
    power_consumption = db.Column(db.Float)
    power_supply = db.Column(db.String(255))
    last_checked = db.Column(db.DateTime)
    ping_time = db.Column(db.Float, default=0.0)

    manufacturer = db.Column(db.String(64))
    owner = db.Column(db.String(64))
    department = db.Column(db.String(100))
    purchase_date = db.Column(db.Date)
    warranty_expiry = db.Column(db.Date)

    os_version = db.Column(db.String(128))
    software_info = db.Column(db.Text)

    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    last_scanned = db.Column(db.DateTime)
    # 自动发现增强字段
    discovery_source = db.Column(db.String(32))       # snmp/lldp/cdp/arp/fdb/import/manual
    external_ref = db.Column(db.String(255))          # 外部系统引用，如 LibreNMS/NetBox ID
    discovery_confidence = db.Column(db.Integer, default=100)
    approval_status = db.Column(db.String(20), default='approved', index=True)  # pending/review/approved/rejected
    last_seen = db.Column(db.DateTime)                # 最近一次自动发现确认时间
    managed_by = db.Column(db.String(32))             # self/librenms/opennms/netbox/manual

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'management_ip': self.management_ip or '',
            'ip_address': self.ip_address or '',
            'position_u': self.position_u,
            'height_u': self.height_u,
            'device_type': self.device_type or 'server',
            'brand': self.brand or '',
            'model': self.model or '',
            'status': self.status or 'active',
            'is_decommissioned': self.is_decommissioned or False,
            'is_wireless_controller': self.is_wireless_controller or False,
            'controller_vendor': self.controller_vendor or 'auto',
            'mac_address': self.mac_address or '',
            'bmc_ip': self.bmc_ip or '',
            'bmc_mac': self.bmc_mac or '',
            'virtualization_type': self.virtualization_type or '',
            'is_virtual_host': self.is_virtual_host or False,
            'description': self.description or '',
            'discovery_source': self.discovery_source or '',
            'external_ref': self.external_ref or '',
            'discovery_confidence': self.discovery_confidence or 100,
            'approval_status': self.approval_status or 'approved',
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'managed_by': self.managed_by or '',
            'cabinet_id': self.cabinet_id
        }

    def __repr__(self):
        return f'<Device {self.name}>'

    spare_parts = db.relationship(
        'SparePart',
        back_populates='installed_device',
        cascade='all, delete-orphan'
    )

class Interface(db.Model):
    __tablename__ = 'interfaces'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    name = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(256))
    type = db.Column(db.String(50), default='Ethernet')
    vlan = db.Column(db.String(20))
    mac_address = db.Column(db.String(17))
    ip_address = db.Column(db.String(45))
    subnet_mask = db.Column(db.String(45))
    ifindex = db.Column(db.Integer, nullable=True)
    admin_status = db.Column(db.String(20))
    oper_status = db.Column(db.String(20))
    speed = db.Column(db.BigInteger)
    mtu = db.Column(db.Integer)
    in_utilization = db.Column(db.Float)
    out_utilization = db.Column(db.Float)
    in_bandwidth = db.Column(db.BigInteger)
    out_bandwidth = db.Column(db.BigInteger)
    in_errors = db.Column(db.Integer)
    out_errors = db.Column(db.Integer)
    in_drops = db.Column(db.Integer)
    out_drops = db.Column(db.Integer)
    neighbor_device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
    neighbor_interface = db.Column(db.String(64))
    neighbor_ip = db.Column(db.String(45))
    neighbor_mac = db.Column(db.String(17))
    discovery_protocol = db.Column(db.String(20))
    last_discovered = db.Column(db.DateTime)
    snmp_index = Column(Integer, nullable=True)
    status = Column(String(20), default='unknown')
    speed_mbps = Column(Integer, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f'<Interface {self.name} on Device {self.device_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'name': self.name,
            'description': self.description,
            'mac_address': self.mac_address,
            'ip_address': self.ip_address,
            'admin_status': self.admin_status,
            'oper_status': self.oper_status,
            'speed': self.speed,
            'in_utilization': self.in_utilization,
            'out_utilization': self.out_utilization,
            'in_bandwidth': self.in_bandwidth,
            'out_bandwidth': self.out_bandwidth,
            'neighbor_device_id': self.neighbor_device_id,
            'neighbor_interface': self.neighbor_interface,
            'neighbor_ip': self.neighbor_ip,
            'vlan': self.vlan,
            'type': self.type
        }

class DeviceComponent(db.Model):
    """设备硬件部件清单（ENTITY-MIB entPhysicalTable 采集）。

    对标 iMC/U-Center 的"板卡/模块资产"，实现设备自动添加的资产闭环：
    机箱序列号回填 Device.serial_number，板卡/电源/风扇明细入本表。
    同一设备的物理实体以 (device_id, physical_index) 唯一。
    """
    __tablename__ = 'device_components'
    __table_args__ = (
        db.UniqueConstraint('device_id', 'physical_index', name='uq_device_component_phys_idx'),
        db.Index('ix_device_components_device_id', 'device_id'),
        db.Index('ix_device_components_serial', 'serial_number'),
    )

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    physical_index = db.Column(db.Integer, nullable=False)       # entPhysicalIndex
    parent_index = db.Column(db.Integer, nullable=True)          # entPhysicalContainedIn
    entity_class = db.Column(db.String(32), index=True)          # chassis/module/powerSupply/fan/sensor/port/cpu...
    name = db.Column(db.String(128))                             # entPhysicalName
    description = db.Column(db.String(256))                      # entPhysicalDescr
    model_name = db.Column(db.String(128))                       # entPhysicalModelName
    serial_number = db.Column(db.String(64), index=True)         # entPhysicalSerialNum
    hardware_rev = db.Column(db.String(64))                      # entPhysicalHardwareRev
    firmware_rev = db.Column(db.String(64))                      # entPhysicalFirmwareRev
    software_rev = db.Column(db.String(64))                      # entPhysicalSoftwareRev
    mfg_name = db.Column(db.String(64))                          # entPhysicalMfgName
    is_fru = db.Column(db.Boolean, default=False)                # entPhysicalIsFRU（可现场更换）
    last_seen = db.Column(db.DateTime, default=_utcnow)          # 最近一次采集到
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    # cascade 必须显式声明：device_id 为 NOT NULL，若按默认行为（解除关联）ORM 会在
    # 删除设备时发 UPDATE device_components SET device_id=NULL → pymysql 1048。
    device = db.relationship(
        'Device',
        backref=db.backref('components', cascade='all, delete-orphan'),
        lazy='select',
    )

    def __repr__(self):
        return f'<DeviceComponent {self.entity_class} {self.name or self.description} device={self.device_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'physical_index': self.physical_index,
            'parent_index': self.parent_index,
            'entity_class': self.entity_class or '',
            'name': self.name or '',
            'description': self.description or '',
            'model_name': self.model_name or '',
            'serial_number': self.serial_number or '',
            'hardware_rev': self.hardware_rev or '',
            'firmware_rev': self.firmware_rev or '',
            'software_rev': self.software_rev or '',
            'mfg_name': self.mfg_name or '',
            'is_fru': bool(self.is_fru),
            'last_seen': self.last_seen.strftime('%Y-%m-%d %H:%M:%S') if self.last_seen else '',
        }


class InventoryTransaction(db.Model):
    __tablename__ = 'inventory_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
    transaction_type = db.Column(db.String(20), nullable=False)
    from_location = db.Column(db.String(100))
    to_location = db.Column(db.String(100))
    quantity = db.Column(db.Integer, default=1)
    transaction_date = db.Column(db.DateTime, default=_utcnow)
    operator = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    
    def __repr__(self):
        return f'<InventoryTransaction {self.transaction_type} for device {self.device_id}>'

class OperationLog(db.Model):
    __tablename__ = 'operation_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    username = db.Column(db.String(64))
    operation_type = db.Column(db.String(64), nullable=False)
    resource_type = db.Column(db.String(64))
    resource_id = db.Column(db.Integer)
    resource_name = db.Column(db.String(256))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    
    def __repr__(self):
        return f'<OperationLog {self.operation_type} {self.resource_type} by {self.username}>'

class InterfaceRelationship(db.Model):
    __tablename__ = 'interface_relationship'
    
    id = db.Column(db.Integer, primary_key=True)
    local_device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    remote_device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
    local_interface = db.Column(db.String(50))
    remote_interface = db.Column(db.String(50))
    connection_type = db.Column(db.String(50))
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=_utcnow)

class TopologyLog(db.Model):
    __tablename__ = 'topology_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    check_time = db.Column(db.DateTime, default=_utcnow)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
    interface_relationship_id = db.Column(db.Integer, db.ForeignKey('interface_relationship.id'))
    log_type = db.Column(db.String(20))
    message = db.Column(db.Text)

class TaskSchedule(db.Model):
    __tablename__ = 'task_schedules'
    
    id = db.Column(db.Integer, primary_key=True)
    task_name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    task_description = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    schedule_type = db.Column(db.String(20), default='interval')
    schedule_value = db.Column(db.Text)
    last_run = db.Column(db.DateTime, nullable=True)
    next_run = db.Column(db.DateTime, nullable=True)
    run_count = db.Column(db.Integer, default=0)
    last_status = db.Column(db.String(20), default='idle')
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    
    def __repr__(self):
        return f'<TaskSchedule {self.task_name} {"✓" if self.is_active else "✗"}>'

class DeviceMonitorLog(db.Model):
    __tablename__ = 'device_monitor_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    device_ip = db.Column(db.String(45), nullable=False)
    old_status = db.Column(db.String(20))
    new_status = db.Column(db.String(20))
    ping_time = db.Column(db.Float, default=0)
    is_online = db.Column(db.Boolean, default=False)
    error_message = db.Column(db.Text)
    monitor_type = db.Column(db.String(20), default='auto_ping', index=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    
    def __repr__(self):
        return f'<DeviceMonitorLog {self.device_ip} {"✓" if self.is_online else "✗"}>'

class Config(db.Model):
    __tablename__ = 'configs'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    
    def __repr__(self):
        return f'<Config {self.key}={self.value}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'value': self.value,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class MonitorData(db.Model):
    __tablename__ = 'monitor_data'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    cpu_usage = db.Column(db.Float)
    memory_usage = db.Column(db.Float)
    disk_usage = db.Column(db.Float)
    network_in = db.Column(db.BigInteger)
    network_out = db.Column(db.BigInteger)
    temperature = db.Column(db.Float)
    power_consumption = db.Column(db.Float)
    uptime = db.Column(db.BigInteger)
    ping_time = db.Column(db.Float)
    ssh_response = db.Column(db.Float)
    snmp_response = db.Column(db.Float)
    is_reachable = db.Column(db.Boolean, default=False)
    has_errors = db.Column(db.Boolean, default=False)
    monitor_type = db.Column(db.String(20), default='auto')
    collected_at = db.Column(db.DateTime, default=_utcnow, index=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    
    __table_args__ = (
        db.Index('idx_device_collected', 'device_id', 'collected_at'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'cpu_usage': self.cpu_usage,
            'memory_usage': self.memory_usage,
            'disk_usage': self.disk_usage,
            'network_in': self.network_in,
            'network_out': self.network_out,
            'temperature': self.temperature,
            'ping_time': self.ping_time,
            'is_reachable': self.is_reachable,
            'collected_at': self.collected_at.isoformat() if self.collected_at else None,
        }
    
    def __repr__(self):
        return f'<MonitorData device={self.device_id} at {self.collected_at}>'

class AlertRule(db.Model):
    __tablename__ = 'alert_rules'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    metric_type = db.Column(db.String(50), nullable=False)
    condition = db.Column(db.String(10), nullable=False)
    threshold = db.Column(db.Float, nullable=False)
    duration = db.Column(db.Integer, default=60)
    severity = db.Column(db.String(20), default='warning')
    apply_to_all = db.Column(db.Boolean, default=True)
    device_ids = db.Column(db.Text)
    device_types = db.Column(db.Text)
    enabled = db.Column(db.Boolean, default=True)
    notify_email = db.Column(db.Boolean, default=False)
    notify_sms = db.Column(db.Boolean, default=False)
    notify_webhook = db.Column(db.Boolean, default=False)
    notify_users = db.Column(db.Text)
    silence_duration = db.Column(db.Integer, default=300)
    repeat_interval = db.Column(db.Integer, default=300)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<AlertRule {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'metric_type': self.metric_type,
            'condition': self.condition,
            'threshold': self.threshold,
            'severity': self.severity,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class AlertEvent(db.Model):
    __tablename__ = 'alert_events'
    
    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('alert_rules.id'))
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(20), nullable=False)
    metric_type = db.Column(db.String(50))
    metric_value = db.Column(db.Float)
    status = db.Column(db.String(20), default='active')
    acknowledged_at = db.Column(db.DateTime)
    acknowledged_by = db.Column(db.String(64))
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.String(64))
    resolved_note = db.Column(db.Text)
    first_occurred = db.Column(db.DateTime, default=_utcnow)
    last_occurred = db.Column(db.DateTime, default=_utcnow)
    occurrence_count = db.Column(db.Integer, default=1)
    notified = db.Column(db.Boolean, default=False)
    notification_sent_at = db.Column(db.DateTime)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True)
    suppressed = db.Column(db.Boolean, default=False, comment='被关联规则抑制(去重)')
    correlation_group = db.Column(db.String(100), comment='关联分组键(同组事件视为同一来源)')
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    
    __table_args__ = (
        db.Index('idx_device_status', 'device_id', 'status'),
        db.Index('idx_severity_status', 'severity', 'status'),
    )
    
    work_order = db.relationship('WorkOrder', backref='alert_events')

    def __repr__(self):
        return f'<AlertEvent {self.title} - {self.severity}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'rule_id': self.rule_id,
            'device_id': self.device_id,
            'title': self.title,
            'message': self.message,
            'severity': self.severity,
            'status': self.status,
            'first_occurred': self.first_occurred.isoformat() if self.first_occurred else None,
            'last_occurred': self.last_occurred.isoformat() if self.last_occurred else None,
            'occurrence_count': self.occurrence_count,
            'device_name': self.device.name if self.device else None,
            'device_ip': self.device.ip_address if self.device else None,
            'work_order_id': self.work_order_id,
        }

class InterfaceMonitorData(db.Model):
    __tablename__ = 'interface_monitor_data'
    
    id = db.Column(db.Integer, primary_key=True)
    interface_id = db.Column(db.Integer, db.ForeignKey('interfaces.id'), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    bytes_in = db.Column(db.BigInteger, default=0)
    bytes_out = db.Column(db.BigInteger, default=0)
    packets_in = db.Column(db.BigInteger, default=0)
    packets_out = db.Column(db.BigInteger, default=0)
    errors_in = db.Column(db.Integer, default=0)
    errors_out = db.Column(db.Integer, default=0)
    drops_in = db.Column(db.Integer, default=0)
    drops_out = db.Column(db.Integer, default=0)
    speed_in = db.Column(db.Float, nullable=True)
    speed_out = db.Column(db.Float, nullable=True)
    bandwidth_usage = db.Column(db.Float)
    admin_status = db.Column(db.String(20))
    oper_status = db.Column(db.String(20))
    speed = db.Column(db.BigInteger)
    collected_at = db.Column(db.DateTime, default=_utcnow, index=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    
    __table_args__ = (
        db.Index('idx_interface_collected', 'interface_id', 'collected_at'),
        db.Index('idx_device_interface', 'device_id', 'interface_id'),
    )
    
    def __repr__(self):
        return f'<InterfaceMonitorData interface={self.interface_id} at {self.collected_at}>'



class ConnectionPath(db.Model):
    __tablename__ = 'connection_paths'
    
    id = db.Column(db.Integer, primary_key=True)
    source_device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    target_device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    source_interface_id = db.Column(db.Integer, db.ForeignKey('interfaces.id'))
    target_interface_id = db.Column(db.Integer, db.ForeignKey('interfaces.id'))
    source_port = db.Column(db.String(64), nullable=False)
    target_port = db.Column(db.String(64), nullable=False)
    connection_type = db.Column(db.String(20), default='physical')
    link_status = db.Column(db.String(20), default='unknown', index=True)
    bandwidth = db.Column(db.BigInteger)  # 带宽 (bps)
    media_type = db.Column(db.String(50))  # 介质类型 (e.g., fiber, copper)
    vlan_id = db.Column(db.String(50))  # VLAN ID 或范围
    discovered_by = db.Column(db.String(50))  # 发现协议或方法
    discovery_protocol = db.Column(db.String(50))  # 新增：具体的发现协议
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    discovery_time = db.Column(db.DateTime)
    tx_bytes = db.Column(db.BigInteger, default=0)
    rx_bytes = db.Column(db.BigInteger, default=0)
    tx_errors = db.Column(db.BigInteger, default=0)
    rx_errors = db.Column(db.BigInteger, default=0)
    confidence = db.Column(db.Integer, default=0)  # 置信度 (0-100)
    last_seen = db.Column(db.DateTime)  # 最近一次发现/验证确认该链路仍存在的时刻（用于老化判断）
    auto_discovered = db.Column(db.Boolean, default=False)  # 是否由自动发现（LLDP等）创建，区别于手工录入
    neighbor_managed = db.Column(db.Boolean, default=True)  # 对端是否在资产库中受管；未受管的邻居（如未知AP）为 False
    link_role = db.Column(db.String(20), default='normal')  # 链路角色：normal / edge_ap（AP等边缘设备单上行）

    def __repr__(self):
        return f'<ConnectionPath {self.source_port} -> {self.target_port}>'




class MonitorSetting(db.Model):
    __tablename__ = 'monitor_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.Text, nullable=False)
    setting_type = db.Column(db.String(50), default='string')
    category = db.Column(db.String(50), default='general')
    scope = db.Column(db.String(20), default='global')
    target_id = db.Column(db.Integer, nullable=True)
    description = db.Column(db.Text)
    enabled = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    updated_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<MonitorSetting {self.setting_key}>'
    
    def get_value(self):
        try:
            if self.setting_type == 'json':
                return json.loads(self.setting_value) if self.setting_value else {}
            elif self.setting_type == 'array':
                return json.loads(self.setting_value) if self.setting_value else []
            elif self.setting_type == 'number':
                return float(self.setting_value) if self.setting_value else 0
            elif self.setting_type == 'boolean':
                return self.setting_value.lower() in ('true', '1', 'yes') if self.setting_value else False
            else:
                return self.setting_value
        except (json.JSONDecodeError, ValueError):
            return self.setting_value
    
    def set_value(self, value):
        if isinstance(value, dict):
            self.setting_type = 'json'
            self.setting_value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, list):
            self.setting_type = 'array'
            self.setting_value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            self.setting_type = 'boolean'
            self.setting_value = str(value).lower()
        elif isinstance(value, (int, float)):
            self.setting_type = 'number'
            self.setting_value = str(value)
        else:
            self.setting_type = 'string'
            self.setting_value = str(value) if value is not None else ''
    
    def to_dict(self):
        return {
            'id': self.id,
            'key': self.setting_key,
            'value': self.get_value(),
            'type': self.setting_type,
            'category': self.category,
            'scope': self.scope,
            'target_id': self.target_id,
            'description': self.description,
            'enabled': self.enabled,
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

class MonitorSchedule(db.Model):
    __tablename__ = 'monitor_schedules'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text)
    monitor_type = db.Column(db.String(50), nullable=False)
    target_type = db.Column(db.String(20), default='all')
    target_value = db.Column(db.Text)
    schedule_type = db.Column(db.String(20), default='interval')
    interval_seconds = db.Column(db.Integer, default=60)
    cron_expression = db.Column(db.String(100))
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    weekdays = db.Column(db.String(50))
    enabled = db.Column(db.Boolean, default=True)
    last_run = db.Column(db.DateTime)
    next_run = db.Column(db.DateTime)
    last_status = db.Column(db.String(20), default='idle')
    last_error = db.Column(db.Text)
    run_count = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    fail_count = db.Column(db.Integer, default=0)
    avg_duration = db.Column(db.Float)
    config = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<MonitorSchedule {self.name}>'
    
    def get_config(self):
        try:
            return json.loads(self.config) if self.config else {}
        except json.JSONDecodeError:
            return {}
    
    def set_config(self, config_dict):
        self.config = json.dumps(config_dict, ensure_ascii=False) if config_dict else '{}'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'monitor_type': self.monitor_type,
            'target_type': self.target_type,
            'target_value': json.loads(self.target_value) if self.target_value else None,
            'schedule_type': self.schedule_type,
            'interval_seconds': self.interval_seconds,
            'cron_expression': self.cron_expression,
            'enabled': self.enabled,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'last_status': self.last_status,
            'run_count': self.run_count,
            'success_count': self.success_count,
            'fail_count': self.fail_count,
            'config': self.get_config(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class NotificationConfig(db.Model):
    __tablename__ = 'notification_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text)
    notification_type = db.Column(db.String(50), nullable=False)
    receivers = db.Column(db.Text)
    receiver_groups = db.Column(db.Text)
    trigger_on = db.Column(db.String(50), default='all')
    trigger_delay = db.Column(db.Integer, default=0)
    max_notifications = db.Column(db.Integer, default=10)
    title_template = db.Column(db.Text)
    message_template = db.Column(db.Text)
    config = db.Column(db.Text)
    enabled = db.Column(db.Boolean, default=True)
    last_notified = db.Column(db.DateTime)
    notification_count = db.Column(db.Integer, default=0)
    test_status = db.Column(db.String(20))
    test_message = db.Column(db.Text)
    last_tested = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<NotificationConfig {self.name}>'
    
    def get_config(self):
        try:
            return json.loads(self.config) if self.config else {}
        except json.JSONDecodeError:
            return {}
    
    def set_config(self, config_dict):
        self.config = json.dumps(config_dict, ensure_ascii=False) if config_dict else '{}'
    
    def get_receivers(self):
        try:
            return json.loads(self.receivers) if self.receivers else []
        except json.JSONDecodeError:
            return []
    
    def set_receivers(self, receivers_list):
        self.receivers = json.dumps(receivers_list, ensure_ascii=False) if receivers_list else '[]'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'notification_type': self.notification_type,
            'receivers': self.get_receivers(),
            'trigger_on': self.trigger_on,
            'enabled': self.enabled,
            'config': self.get_config(),
            'test_status': self.test_status,
            'test_message': self.test_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

class AlertAction(db.Model):
    __tablename__ = 'alert_actions'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text)
    action_type = db.Column(db.String(50), nullable=False)
    trigger_on_severity = db.Column(db.String(50), default='all')
    trigger_on_status = db.Column(db.String(50), default='active')
    execute_after = db.Column(db.Integer, default=0)
    max_executions = db.Column(db.Integer, default=1)
    cooldown_period = db.Column(db.Integer, default=300)
    script_path = db.Column(db.Text)
    script_arguments = db.Column(db.Text)
    api_url = db.Column(db.Text)
    api_method = db.Column(db.String(10), default='POST')
    api_headers = db.Column(db.Text)
    api_body = db.Column(db.Text)
    command = db.Column(db.Text)
    command_timeout = db.Column(db.Integer, default=30)
    notification_config_id = db.Column(db.Integer, db.ForeignKey('notification_configs.id'))
    variable_mapping = db.Column(db.Text)
    enabled = db.Column(db.Boolean, default=True)
    last_executed = db.Column(db.DateTime)
    execution_count = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    fail_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<AlertAction {self.name}>'
    
    def get_script_arguments(self):
        try:
            return json.loads(self.script_arguments) if self.script_arguments else {}
        except json.JSONDecodeError:
            return {}
    
    def set_script_arguments(self, args_dict):
        self.script_arguments = json.dumps(args_dict, ensure_ascii=False) if args_dict else '{}'
    
    def get_api_headers(self):
        try:
            return json.loads(self.api_headers) if self.api_headers else {}
        except json.JSONDecodeError:
            return {}
    
    def set_api_headers(self, headers_dict):
        self.api_headers = json.dumps(headers_dict, ensure_ascii=False) if headers_dict else '{}'
    
    def get_api_body(self):
        try:
            return json.loads(self.api_body) if self.api_body else {}
        except json.JSONDecodeError:
            return {}
    
    def set_api_body(self, body_dict):
        self.api_body = json.dumps(body_dict, ensure_ascii=False) if body_dict else '{}'
    
    def get_variable_mapping(self):
        try:
            return json.loads(self.variable_mapping) if self.variable_mapping else {}
        except json.JSONDecodeError:
            return {}
    
    def set_variable_mapping(self, mapping_dict):
        self.variable_mapping = json.dumps(mapping_dict, ensure_ascii=False) if mapping_dict else '{}'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'action_type': self.action_type,
            'trigger_on_severity': self.trigger_on_severity,
            'trigger_on_status': self.trigger_on_status,
            'enabled': self.enabled,
            'execution_count': self.execution_count,
            'success_count': self.success_count,
            'fail_count': self.fail_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class DeviceMonitorConfig(db.Model):
    __tablename__ = 'device_monitor_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    enable_ping = db.Column(db.Boolean, default=True)
    enable_snmp = db.Column(db.Boolean, default=False)
    enable_ssh = db.Column(db.String(20), default='auto')
    enable_api = db.Column(db.Boolean, default=False)
    ping_interval = db.Column(db.Integer, default=60)
    snmp_interval = db.Column(db.Integer, default=300)
    ssh_interval = db.Column(db.Integer, default=300)
    api_interval = db.Column(db.Integer, default=300)
    ping_timeout = db.Column(db.Float, default=2.0)
    snmp_timeout = db.Column(db.Float, default=5.0)
    ssh_timeout = db.Column(db.Float, default=10.0)
    api_timeout = db.Column(db.Float, default=5.0)
    retry_count = db.Column(db.Integer, default=3)
    retry_interval = db.Column(db.Integer, default=5)
    snmp_version = db.Column(db.Integer, default=2)
    snmp_community = db.Column(db.String(64))
    snmp_username = db.Column(db.String(64))
    snmp_auth_password = db.Column(db.String(255))
    snmp_priv_password = db.Column(db.String(255))
    snmp_auth_protocol = db.Column(db.String(20))
    snmp_priv_protocol = db.Column(db.String(20))
    ssh_username = db.Column(db.String(64))
    ssh_password = db.Column(db.String(255))
    ssh_key_file = db.Column(db.Text)
    ssh_port = db.Column(db.Integer, default=22)
    api_url = db.Column(db.String(500))
    api_method = db.Column(db.String(10), default='GET')
    api_headers = db.Column(db.Text)
    api_body = db.Column(db.Text)
    api_auth_type = db.Column(db.String(20))
    api_auth_value = db.Column(db.Text)
    custom_script = db.Column(db.Text)
    custom_script_timeout = db.Column(db.Integer, default=30)
    monitor_metrics = db.Column(db.Text)
    inherit_alerts = db.Column(db.Boolean, default=True)
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    
    __table_args__ = (
        db.UniqueConstraint('device_id', name='uq_device_monitor_config'),
    )
    
    def __repr__(self):
        return f'<DeviceMonitorConfig device={self.device_id}>'
    
    def get_monitor_metrics(self):
        try:
            return json.loads(self.monitor_metrics) if self.monitor_metrics else {}
        except json.JSONDecodeError:
            return {}
    
    def set_monitor_metrics(self, metrics_dict):
        self.monitor_metrics = json.dumps(metrics_dict, ensure_ascii=False) if metrics_dict else '{}'
    
    def get_api_headers(self):
        try:
            return json.loads(self.api_headers) if self.api_headers else {}
        except json.JSONDecodeError:
            return {}
    
    def set_api_headers(self, headers_dict):
        self.api_headers = json.dumps(headers_dict, ensure_ascii=False) if headers_dict else '{}'
    
    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'enable_ping': self.enable_ping,
            'enable_snmp': self.enable_snmp,
            'enable_ssh': self.enable_ssh,
            'enable_api': self.enable_api,
            'ping_interval': self.ping_interval,
            'snmp_interval': self.snmp_interval,
            'ssh_interval': self.ssh_interval,
            'api_interval': self.api_interval,
            'ping_timeout': self.ping_timeout,
            'snmp_timeout': self.snmp_timeout,
            'ssh_timeout': self.ssh_timeout,
            'api_timeout': self.api_timeout,
            'retry_count': self.retry_count,
            'retry_interval': self.retry_interval,
            'snmp_version': self.snmp_version,
            'snmp_community': self.snmp_community,
            'ssh_username': self.ssh_username,
            'ssh_port': self.ssh_port,
            'api_url': self.api_url,
            'api_method': self.api_method,
            'api_headers': self.get_api_headers(),
            'enabled': self.enabled,
            'device_name': self.device.name if self.device else None,
            'device_ip': self.device.management_ip if self.device else None,
        }

class TopologySetting(db.Model):
    __tablename__ = 'topology_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.Text, nullable=False)
    setting_type = db.Column(db.String(50), default='string')
    category = db.Column(db.String(50), default='discovery')
    description = db.Column(db.Text)
    enabled = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    updated_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<TopologySetting {self.setting_key}>'
    
    def get_value(self):
        try:
            if self.setting_type == 'json':
                return json.loads(self.setting_value) if self.setting_value else {}
            elif self.setting_type == 'array':
                return json.loads(self.setting_value) if self.setting_value else []
            elif self.setting_type == 'number':
                return float(self.setting_value) if self.setting_value else 0
            elif self.setting_type == 'boolean':
                return self.setting_value.lower() in ('true', '1', 'yes') if self.setting_value else False
            else:
                return self.setting_value
        except (json.JSONDecodeError, ValueError):
            return self.setting_value
    
    def set_value(self, value):
        if isinstance(value, dict):
            self.setting_type = 'json'
            self.setting_value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, list):
            self.setting_type = 'array'
            self.setting_value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            self.setting_type = 'boolean'
            self.setting_value = str(value).lower()
        elif isinstance(value, (int, float)):
            self.setting_type = 'number'
            self.setting_value = str(value)
        else:
            self.setting_type = 'string'
            self.setting_value = str(value) if value is not None else ''
    
    def to_dict(self):
        return {
            'id': self.id,
            'key': self.setting_key,
            'value': self.get_value(),
            'type': self.setting_type,
            'category': self.category,
            'description': self.description,
            'enabled': self.enabled,
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

class DiscoveryTask(db.Model):
    __tablename__ = 'discovery_tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text)
    discovery_mode = db.Column(db.String(20), nullable=False, default='protocol')
    discovery_type = db.Column(db.String(50), nullable=False)
    target_type = db.Column(db.String(20), default='subnet')
    target_value = db.Column(db.Text)
    core_device_id = db.Column(db.Integer, nullable=True)
    access_device_ids = db.Column(db.Text, nullable=True)
    schedule_type = db.Column(db.String(20), default='manual')
    interval_seconds = db.Column(db.Integer, default=3600)
    cron_expression = db.Column(db.String(100))
    max_depth = db.Column(db.Integer, default=3)
    max_hops = db.Column(db.Integer, default=10)
    use_lldp = db.Column(db.Boolean, default=True)
    use_cdp = db.Column(db.Boolean, default=True)
    use_snmp = db.Column(db.Boolean, default=True)
    use_icmp = db.Column(db.Boolean, default=True)
    use_arp = db.Column(db.Boolean, default=True)
    use_snmp_mac = db.Column(db.Boolean, default=False)
    snmp_community = db.Column(db.String(64), default='public')
    snmp_version = db.Column(db.Integer, default=2)
    snmp_timeout = db.Column(db.Integer, default=5)
    snmp_retries = db.Column(db.Integer, default=3)
    max_threads = db.Column(db.Integer, default=10)
    scan_timeout = db.Column(db.Integer, default=30)
    rate_limit = db.Column(db.Integer, default=100)
    auto_save = db.Column(db.Boolean, default=True)
    overwrite_existing = db.Column(db.Boolean, default=False)
    create_missing = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(20), default='idle')
    enabled = db.Column(db.Boolean, default=True)
    progress = db.Column(db.Integer, default=0)
    last_run = db.Column(db.DateTime)
    next_run = db.Column(db.DateTime)
    last_duration = db.Column(db.Float)
    # /24 及以上网段的扫描结果可能超过 MySQL TEXT 上限(65535字节)，
    # 使用 MEDIUMTEXT(16MB) 存储，避免写入失败导致任务卡在 running
    last_result = db.Column(db.Text().with_variant(MEDIUMTEXT(), 'mysql'))
    run_count = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    fail_count = db.Column(db.Integer, default=0)
    discovered_count = db.Column(db.Integer, default=0)
    connection_count = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)
    error_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))

    def __repr__(self):
        return f'<DiscoveryTask {self.name}>'
    
    def get_target_value(self):
        try:
            return json.loads(self.target_value) if self.target_value else {}
        except json.JSONDecodeError:
            return {}
    
    def set_target_value(self, value_dict):
        self.target_value = json.dumps(value_dict, ensure_ascii=False) if value_dict else '{}'
    
    def get_access_device_ids(self):
        """始终返回设备 ID 列表"""
        if not self.access_device_ids:
            return []
        if isinstance(self.access_device_ids, list):
            return self.access_device_ids
        if isinstance(self.access_device_ids, int):
            return [self.access_device_ids]
        # 假设存储的是 JSON 字符串
        if self.access_device_ids.startswith('['):
            return json.loads(self.access_device_ids)
        # 假设存储的是逗号分隔字符串
        return [int(x.strip()) for x in self.access_device_ids.split(',') if x.strip()]
    
    def set_access_device_ids(self, id_list):
        self.access_device_ids = json.dumps(id_list, ensure_ascii=False) if id_list else '[]'
    
    def get_last_result(self):
        try:
            return json.loads(self.last_result) if self.last_result else {}
        except json.JSONDecodeError:
            return {}
    
    def set_last_result(self, result_dict):
        self.last_result = json.dumps(result_dict, ensure_ascii=False) if result_dict else '{}'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'discovery_mode': self.discovery_mode,
            'discovery_type': self.discovery_type,
            'target_type': self.target_type,
            'target_value': self.get_target_value(),
            'core_device_id': self.core_device_id,
            'access_device_ids': self.get_access_device_ids(),
            'schedule_type': self.schedule_type,
            'interval_seconds': self.interval_seconds,
            'cron_expression': self.cron_expression,
            'max_depth': self.max_depth,
            'max_hops': self.max_hops,
            'use_lldp': self.use_lldp,
            'use_cdp': self.use_cdp,
            'use_snmp': self.use_snmp,
            'use_icmp': self.use_icmp,
            'use_arp': self.use_arp,
            'use_snmp_mac': self.use_snmp_mac, 
            'snmp_community': self.snmp_community,
            'snmp_version': self.snmp_version,
            'snmp_timeout': self.snmp_timeout,
            'snmp_retries': self.snmp_retries,
            'max_threads': self.max_threads,
            'scan_timeout': self.scan_timeout,
            'rate_limit': self.rate_limit,
            'auto_save': self.auto_save,
            'overwrite_existing': self.overwrite_existing,
            'create_missing': self.create_missing,
            'status': self.status,
            'enabled': self.enabled,
            'progress': self.progress,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'last_duration': self.last_duration,
            'run_count': self.run_count,
            'success_count': self.success_count,
            'fail_count': self.fail_count,
            'discovered_count': self.discovered_count,
            'connection_count': self.connection_count,
            'last_error': self.last_error,
            'error_count': self.error_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'created_by': self.created_by,
        }

class DiscoveryResult(db.Model):
    __tablename__ = 'discovery_results'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('discovery_tasks.id'), nullable=False, index=True)
    target_ip = db.Column(db.String(45))
    target_hostname = db.Column(db.String(255))
    target_mac = db.Column(db.String(17))
    discovered_ip = db.Column(db.String(45))
    discovered_hostname = db.Column(db.String(255))
    discovered_device_type = db.Column(db.String(50))
    discovered_os = db.Column(db.String(100))
    discovered_mac = db.Column(db.String(17))
    discovered_vendor = db.Column(db.String(100))
    local_interface = db.Column(db.String(50))
    remote_interface = db.Column(db.String(50))
    interface_description = db.Column(db.String(255))
    discovery_protocol = db.Column(db.String(20))
    protocol_data = db.Column(db.Text)
    connection_type = db.Column(db.String(20))
    connection_speed = db.Column(db.BigInteger)
    vlan_id = db.Column(db.String(50))
    is_new_device = db.Column(db.Boolean, default=False)
    is_new_connection = db.Column(db.Boolean, default=False)
    confidence = db.Column(db.Integer, default=100)
    verified = db.Column(db.Boolean, default=False)
    discovered_at = db.Column(db.DateTime, default=_utcnow, index=True)
    processed_at = db.Column(db.DateTime)
    match_device_id = db.Column(db.Integer, nullable=True)
    match_score = db.Column(db.Integer, default=0)
    decision = db.Column(db.String(20), nullable=True)  # create/update/ignore/merge
    error_code = db.Column(db.String(50), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    __table_args__ = (
        db.Index('idx_task_discovered', 'task_id', 'discovered_at'),
        db.Index('idx_target_discovered', 'target_ip', 'discovered_ip'),
    )
    
    def __repr__(self):
        return f'<DiscoveryResult {self.target_ip} -> {self.discovered_ip}>'
    
    def get_protocol_data(self):
        try:
            return json.loads(self.protocol_data) if self.protocol_data else {}
        except json.JSONDecodeError:
            return {}
    
    def set_protocol_data(self, data_dict):
        self.protocol_data = json.dumps(data_dict, ensure_ascii=False) if data_dict else '{}'
    
    def to_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'target_ip': self.target_ip,
            'discovered_ip': self.discovered_ip,
            'discovered_hostname': self.discovered_hostname,
            'discovery_protocol': self.discovery_protocol,
            'local_interface': self.local_interface,
            'remote_interface': self.remote_interface,
            'connection_type': self.connection_type,
            'connection_speed': self.connection_speed,
            'vlan_id': self.vlan_id,
            'is_new_device': self.is_new_device,
            'is_new_connection': self.is_new_connection,
            'confidence': self.confidence,
            'verified': self.verified,
            'match_device_id': self.match_device_id,
            'match_score': self.match_score,
            'decision': self.decision,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'discovered_at': self.discovered_at.isoformat() if self.discovered_at else None,
        }

class LogicalTopology(db.Model):
    __tablename__ = 'logical_topologies'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text)
    topology_type = db.Column(db.String(50), nullable=False)
    group_by = db.Column(db.String(50))
    group_value = db.Column(db.String(100))
    topology_data = db.Column(db.Text)
    layout_type = db.Column(db.String(50), default='hierarchical')
    node_size = db.Column(db.Integer, default=30)
    link_distance = db.Column(db.Integer, default=100)
    show_labels = db.Column(db.Boolean, default=True)
    show_icons = db.Column(db.Boolean, default=True)
    enabled = db.Column(db.Boolean, default=True)
    is_public = db.Column(db.Boolean, default=True)
    node_count = db.Column(db.Integer, default=0)
    link_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<LogicalTopology {self.name}>'
    
    def get_topology_data(self):
        try:
            data = json.loads(self.topology_data) if self.topology_data else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            return {'nodes': [], 'edges': []}
        # 兼容旧数据：保存过用 "links" 键的历史记录统一为 "edges"
        if 'links' in data and 'edges' not in data:
            data['edges'] = data.pop('links')
        if 'nodes' not in data:
            data['nodes'] = []
        if 'edges' not in data:
            data['edges'] = []
        return data

    def set_topology_data(self, data_dict):
        self.topology_data = json.dumps(data_dict, ensure_ascii=False) if data_dict else None
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'topology_type': self.topology_type,
            'group_by': self.group_by,
            'group_value': self.group_value,
            'layout_type': self.layout_type,
            'enabled': self.enabled,
            'is_public': self.is_public,
            'node_count': self.node_count,
            'link_count': self.link_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

class TopologyLayout(db.Model):
    __tablename__ = 'topology_layouts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text)
    layout_type = db.Column(db.String(50), nullable=False)
    layout_data = db.Column(db.Text)
    apply_to = db.Column(db.String(50))
    topology_id = db.Column(db.Integer, db.ForeignKey('logical_topologies.id'))
    node_positions = db.Column(db.Text)
    link_routing = db.Column(db.String(50), default='straight')
    grid_enabled = db.Column(db.Boolean, default=True)
    grid_size = db.Column(db.Integer, default=20)
    snap_to_grid = db.Column(db.Boolean, default=True)
    zoom_level = db.Column(db.Float, default=1.0)
    center_x = db.Column(db.Float, default=0)
    center_y = db.Column(db.Float, default=0)
    show_grid = db.Column(db.Boolean, default=True)
    show_labels = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<TopologyLayout {self.name}>'
    
    def get_layout_data(self):
        try:
            return json.loads(self.layout_data) if self.layout_data else {}
        except json.JSONDecodeError:
            return {}
    
    def set_layout_data(self, data_dict):
        self.layout_data = json.dumps(data_dict, ensure_ascii=False) if data_dict else '{}'
    
    def get_node_positions(self):
        try:
            return json.loads(self.node_positions) if self.node_positions else {}
        except json.JSONDecodeError:
            return {}
    
    def set_node_positions(self, positions_dict):
        self.node_positions = json.dumps(positions_dict, ensure_ascii=False) if positions_dict else '{}'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'layout_type': self.layout_type,
            'apply_to': self.apply_to,
            'topology_id': self.topology_id,
            'link_routing': self.link_routing,
            'grid_enabled': self.grid_enabled,
            'grid_size': self.grid_size,
            'snap_to_grid': self.snap_to_grid,
            'zoom_level': self.zoom_level,
            'center_x': self.center_x,
            'center_y': self.center_y,
            'show_grid': self.show_grid,
            'show_labels': self.show_labels,
            'is_default': self.is_default,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class AlertTemplate(db.Model):
    __tablename__ = 'alert_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text)
    template_type = db.Column(db.String(50), default='device')
    condition_type = db.Column(db.String(20), default='threshold')
    metric_type = db.Column(db.String(50))
    condition_operator = db.Column(db.String(10))
    threshold_value = db.Column(db.Float)
    duration = db.Column(db.Integer, default=60)
    repeat_interval = db.Column(db.Integer, default=300)
    suppress_repeat = db.Column(db.Boolean, default=True)
    severity = db.Column(db.String(20), default='warning')
    title_template = db.Column(db.Text)
    message_template = db.Column(db.Text)
    auto_recover = db.Column(db.Boolean, default=False)
    recover_condition = db.Column(db.String(100))
    recover_message = db.Column(db.Text)
    suggestions = db.Column(db.Text)
    enabled = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<AlertTemplate {self.name}>'
    
    def get_suggestions(self):
        try:
            return json.loads(self.suggestions) if self.suggestions else []
        except json.JSONDecodeError:
            return []
    
    def set_suggestions(self, suggestions_list):
        self.suggestions = json.dumps(suggestions_list, ensure_ascii=False) if suggestions_list else '[]'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'template_type': self.template_type,
            'condition_type': self.condition_type,
            'metric_type': self.metric_type,
            'condition_operator': self.condition_operator,
            'threshold_value': self.threshold_value,
            'duration': self.duration,
            'severity': self.severity,
            'auto_recover': self.auto_recover,
            'enabled': self.enabled,
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class AlertEscalation(db.Model):
    __tablename__ = 'alert_escalations'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text)
    original_severity = db.Column(db.String(20))
    escalate_after = db.Column(db.Integer, default=300)
    escalate_if_unacknowledged = db.Column(db.Boolean, default=True)
    target_severity = db.Column(db.String(20), nullable=False)
    target_users = db.Column(db.Text)
    target_groups = db.Column(db.Text)
    target_actions = db.Column(db.Text)
    escalation_message = db.Column(db.Text)
    enabled = db.Column(db.Boolean, default=True)
    escalation_count = db.Column(db.Integer, default=0)
    # ---- SEL/告警升级联动增强（新增列，可空；patch_schema 幂等补齐）----
    metric_type = db.Column(db.String(50), comment='适用范围: 空/all=全部, bmc_sel=仅iDRAC SEL')
    max_escalations = db.Column(db.Integer, default=3, comment='同一告警最大升级次数')
    repeat_interval = db.Column(db.Integer, default=0, comment='重复升级间隔(秒), 0=仅升级一次')
    auto_create_work_order = db.Column(db.Boolean, default=False, comment='升级后自动创建工单并回链告警')
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<AlertEscalation {self.name}>'
    
    def get_target_users(self):
        try:
            return json.loads(self.target_users) if self.target_users else []
        except json.JSONDecodeError:
            return []
    
    def set_target_users(self, users_list):
        self.target_users = json.dumps(users_list, ensure_ascii=False) if users_list else '[]'
    
    def get_target_groups(self):
        try:
            return json.loads(self.target_groups) if self.target_groups else []
        except json.JSONDecodeError:
            return []
    
    def set_target_groups(self, groups_list):
        self.target_groups = json.dumps(groups_list, ensure_ascii=False) if groups_list else '[]'
    
    def get_target_actions(self):
        try:
            return json.loads(self.target_actions) if self.target_actions else []
        except json.JSONDecodeError:
            return []
    
    def set_target_actions(self, actions_list):
        self.target_actions = json.dumps(actions_list, ensure_ascii=False) if actions_list else '[]'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'original_severity': self.original_severity,
            'escalate_after': self.escalate_after,
            'escalate_if_unacknowledged': self.escalate_if_unacknowledged,
            'target_severity': self.target_severity,
            'metric_type': self.metric_type,
            'max_escalations': self.max_escalations,
            'repeat_interval': self.repeat_interval,
            'auto_create_work_order': self.auto_create_work_order,
            'target_users': self.get_target_users(),
            'target_groups': self.get_target_groups(),
            'target_actions': self.get_target_actions(),
            'escalation_message': self.escalation_message,
            'enabled': self.enabled,
            'escalation_count': self.escalation_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class AlertEscalationLog(db.Model):
    """每次告警升级的历史记录（按 告警 x 策略 记录级别/时间，用于去重与加频）。"""
    __tablename__ = 'alert_escalation_logs'

    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer, db.ForeignKey('alert_events.id'), index=True)
    policy_id = db.Column(db.Integer, db.ForeignKey('alert_escalations.id'), index=True)
    level = db.Column(db.Integer, default=1)
    from_severity = db.Column(db.String(20))
    to_severity = db.Column(db.String(20))
    channel = db.Column(db.String(50))
    target = db.Column(db.Text)
    message = db.Column(db.Text)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), index=True, nullable=True)
    escalated_at = db.Column(db.DateTime, default=_utcnow)

    def __repr__(self):
        return f'<AlertEscalationLog alert={self.alert_id} policy={self.policy_id} lv={self.level}>'


class AlertSuppression(db.Model):
    __tablename__ = 'alert_suppressions'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text)
    match_type = db.Column(db.String(20), default='device')
    match_value = db.Column(db.Text)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    repeat_schedule = db.Column(db.Text)
    suppress_severities = db.Column(db.Text)
    suppress_alert_types = db.Column(db.Text)
    enabled = db.Column(db.Boolean, default=True)
    suppressed_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<AlertSuppression {self.name}>'
    
    def get_match_value(self):
        try:
            return json.loads(self.match_value) if self.match_value else {}
        except json.JSONDecodeError:
            return {}
    
    def set_match_value(self, match_dict):
        self.match_value = json.dumps(match_dict, ensure_ascii=False) if match_dict else '{}'
    
    def get_repeat_schedule(self):
        try:
            return json.loads(self.repeat_schedule) if self.repeat_schedule else {}
        except json.JSONDecodeError:
            return {}
    
    def set_repeat_schedule(self, schedule_dict):
        self.repeat_schedule = json.dumps(schedule_dict, ensure_ascii=False) if schedule_dict else '{}'
    
    def get_suppress_severities(self):
        try:
            return json.loads(self.suppress_severities) if self.suppress_severities else []
        except json.JSONDecodeError:
            return []
    
    def set_suppress_severities(self, severities_list):
        self.suppress_severities = json.dumps(severities_list, ensure_ascii=False) if severities_list else '[]'
    
    def get_suppress_alert_types(self):
        try:
            return json.loads(self.suppress_alert_types) if self.suppress_alert_types else []
        except json.JSONDecodeError:
            return []
    
    def set_suppress_alert_types(self, types_list):
        self.suppress_alert_types = json.dumps(types_list, ensure_ascii=False) if types_list else '[]'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'match_type': self.match_type,
            'enabled': self.enabled,
            'suppressed_count': self.suppressed_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class AlertStatistic(db.Model):
    __tablename__ = 'alert_statistics'
    
    id = db.Column(db.Integer, primary_key=True)
    statistic_type = db.Column(db.String(50), nullable=False)
    period_start = db.Column(db.DateTime, nullable=False, index=True)
    period_end = db.Column(db.DateTime, nullable=False)
    total_alerts = db.Column(db.Integer, default=0)
    active_alerts = db.Column(db.Integer, default=0)
    acknowledged_alerts = db.Column(db.Integer, default=0)
    resolved_alerts = db.Column(db.Integer, default=0)
    critical_alerts = db.Column(db.Integer, default=0)
    error_alerts = db.Column(db.Integer, default=0)
    warning_alerts = db.Column(db.Integer, default=0)
    info_alerts = db.Column(db.Integer, default=0)
    device_type_stats = db.Column(db.Text)
    avg_response_time = db.Column(db.Float)
    avg_resolve_time = db.Column(db.Float)
    source_stats = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    
    __table_args__ = (
        db.Index('idx_statistic_period', 'statistic_type', 'period_start'),
    )
    
    def __repr__(self):
        return f'<AlertStatistic {self.statistic_type} {self.period_start}>'
    
    def get_device_type_stats(self):
        try:
            return json.loads(self.device_type_stats) if self.device_type_stats else {}
        except json.JSONDecodeError:
            return {}
    
    def set_device_type_stats(self, stats_dict):
        self.device_type_stats = json.dumps(stats_dict, ensure_ascii=False) if stats_dict else '{}'
    
    def get_source_stats(self):
        try:
            return json.loads(self.source_stats) if self.source_stats else {}
        except json.JSONDecodeError:
            return {}
    
    def set_source_stats(self, stats_dict):
        self.source_stats = json.dumps(stats_dict, ensure_ascii=False) if stats_dict else '{}'
    
    def to_dict(self):
        return {
            'id': self.id,
            'statistic_type': self.statistic_type,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'total_alerts': self.total_alerts,
            'active_alerts': self.active_alerts,
            'critical_alerts': self.critical_alerts,
            'error_alerts': self.error_alerts,
            'warning_alerts': self.warning_alerts,
            'info_alerts': self.info_alerts,
            'avg_response_time': self.avg_response_time,
            'avg_resolve_time': self.avg_resolve_time,
        }

class MonitorLog(db.Model):
    __tablename__ = 'monitor_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    task_name = db.Column(db.String(100), nullable=False, index=True)
    task_type = db.Column(db.String(50))
    status = db.Column(db.String(20), default='pending')
    result = db.Column(db.Text)
    target_devices = db.Column(db.Text)
    total_devices = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    duration = db.Column(db.Float)
    error_message = db.Column(db.Text)
    error_details = db.Column(db.Text)
    trigger_type = db.Column(db.String(20), default='manual')
    schedule_id = db.Column(db.Integer, db.ForeignKey('monitor_schedules.id'))
    created_at = db.Column(db.DateTime, default=_utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    
    __table_args__ = (
        db.Index('idx_log_status_time', 'status', 'created_at'),
    )
    
    def __repr__(self):
        return f'<MonitorLog {self.task_name} {self.status}>'
    
    def get_result(self):
        try:
            return json.loads(self.result) if self.result else {}
        except json.JSONDecodeError:
            return {}
    
    def set_result(self, result_dict):
        self.result = json.dumps(result_dict, ensure_ascii=False) if result_dict else '{}'
    
    def get_target_devices(self):
        try:
            return json.loads(self.target_devices) if self.target_devices else []
        except json.JSONDecodeError:
            return []
    
    def set_target_devices(self, devices_list):
        self.target_devices = json.dumps(devices_list, ensure_ascii=False) if devices_list else '[]'
    
    def to_dict(self):
        return {
            'id': self.id,
            'task_name': self.task_name,
            'task_type': self.task_type,
            'status': self.status,
            'total_devices': self.total_devices,
            'success_count': self.success_count,
            'failed_count': self.failed_count,
            'duration': self.duration,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class DeviceMonitor(db.Model):
    __tablename__ = 'device_monitors'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, default=True)
    last_monitored = db.Column(db.DateTime)
    last_status = db.Column(db.String(20), default='unknown')
    cpu_status = db.Column(db.String(20), default='normal')
    memory_status = db.Column(db.String(20), default='normal')
    disk_status = db.Column(db.String(20), default='normal')
    network_status = db.Column(db.String(20), default='normal')
    is_reachable = db.Column(db.Boolean, default=False)
    ping_time = db.Column(db.Float)
    ssh_accessible = db.Column(db.Boolean, default=False)
    snmp_accessible = db.Column(db.Boolean, default=False)
    monitor_methods = db.Column(db.Text)
    active_alerts = db.Column(db.Integer, default=0)
    last_alert_time = db.Column(db.DateTime)
    config_version = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    
    def __repr__(self):
        return f'<DeviceMonitor device={self.device_id} status={self.last_status}>'
    
    def get_monitor_methods(self):
        try:
            return json.loads(self.monitor_methods) if self.monitor_methods else {}
        except json.JSONDecodeError:
            return {}
    
    def set_monitor_methods(self, methods_dict):
        self.monitor_methods = json.dumps(methods_dict, ensure_ascii=False) if methods_dict else '{}'
    
    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'enabled': self.enabled,
            'last_status': self.last_status,
            'is_reachable': self.is_reachable,
            'ping_time': self.ping_time,
            'active_alerts': self.active_alerts,
            'last_monitored': self.last_monitored.isoformat() if self.last_monitored else None,
            'device_name': self.device.name if self.device else None,
            'device_ip': self.device.ip_address if self.device else None,
        }

class Alert(db.Model):
    __tablename__ = 'alerts'
    
    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer, db.ForeignKey('alert_events.id'), nullable=False, unique=True, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('alert_rules.id'))
    title = db.Column(db.String(200), nullable=False)
    severity = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')
    acknowledged = db.Column(db.Boolean, default=False)
    resolved = db.Column(db.Boolean, default=False)
    acknowledged_at = db.Column(db.DateTime)
    acknowledged_by = db.Column(db.String(64))
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.String(64))
    first_occurred = db.Column(db.DateTime, default=_utcnow, index=True)
    last_occurred = db.Column(db.DateTime, default=_utcnow)
    occurrence_count = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    
    __table_args__ = (
        db.Index('idx_alert_status_device', 'status', 'device_id'),
        db.Index('idx_alert_severity_time', 'severity', 'first_occurred'),
    )
    
    def __repr__(self):
        return f'<Alert {self.title} - {self.severity}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'alert_id': self.alert_id,
            'device_id': self.device_id,
            'title': self.title,
            'severity': self.severity,
            'status': self.status,
            'acknowledged': self.acknowledged,
            'resolved': self.resolved,
            'first_occurred': self.first_occurred.isoformat() if self.first_occurred else None,
            'last_occurred': self.last_occurred.isoformat() if self.last_occurred else None,
            'occurrence_count': self.occurrence_count,
            'device_name': self.device.name if self.device else None,
            'device_ip': self.device.ip_address if self.device else None,
        }

class GlobalSetting(db.Model):
    __tablename__ = 'global_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.Text)
    setting_type = db.Column(db.String(50), default='string')
    category = db.Column(db.String(50), default='system')
    description = db.Column(db.Text)
    default_value = db.Column(db.Text)
    is_system = db.Column(db.Boolean, default=False)
    editable = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_by = db.Column(db.String(64))
    updated_by = db.Column(db.String(64))
    
    def __repr__(self):
        return f'<GlobalSetting {self.setting_key}>'
    
    def get_value(self):
        try:
            if self.setting_type == 'json':
                return json.loads(self.setting_value) if self.setting_value else {}
            elif self.setting_type == 'array':
                return json.loads(self.setting_value) if self.setting_value else []
            elif self.setting_type == 'number':
                return float(self.setting_value) if self.setting_value else 0
            elif self.setting_type == 'boolean':
                return self.setting_value.lower() in ('true', '1', 'yes') if self.setting_value else False
            else:
                return self.setting_value
        except (json.JSONDecodeError, ValueError):
            return self.setting_value
    
    def set_value(self, value):
        if isinstance(value, dict):
            self.setting_type = 'json'
            self.setting_value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, list):
            self.setting_type = 'array'
            self.setting_value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            self.setting_type = 'boolean'
            self.setting_value = str(value).lower()
        elif isinstance(value, (int, float)):
            self.setting_type = 'number'
            self.setting_value = str(value)
        else:
            self.setting_type = 'string'
            self.setting_value = str(value) if value is not None else ''
    
    def to_dict(self):
        return {
            'id': self.id,
            'key': self.setting_key,
            'value': self.get_value(),
            'type': self.setting_type,
            'category': self.category,
            'description': self.description,
            'is_system': self.is_system,
            'editable': self.editable,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

class PerformanceMetric(db.Model):
    __tablename__ = 'performance_metrics'
    
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey('devices.id'), nullable=False)
    cpu_usage = Column(Float, nullable=True)
    memory_usage = Column(Float, nullable=True)
    network_usage = Column(Float, nullable=True)
    disk_usage = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=_utcnow)
    created_at = Column(DateTime, default=_utcnow)

class MonitoringSetting(db.Model):
    __tablename__ = 'monitoring_settings'
    
    id = Column(Integer, primary_key=True)
    setting_key = Column(String(100), nullable=False, index=True)
    setting_value = Column(Text, nullable=True)
    data_type = Column(String(50), default='string')
    category = Column(String(50), default='general', index=True)
    description = Column(String(500), nullable=True)
    min_value = Column(Integer, nullable=True)
    max_value = Column(Integer, nullable=True)
    options = Column(Text, nullable=True)
    display_name = Column(String(200), nullable=True)
    is_default = Column(Boolean, default=False)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    created_by = Column(String(100))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(String(100))
    
    __table_args__ = (db.UniqueConstraint('setting_key', 'category', name='uq_setting_key_category'),)
    
    def get_value(self):
        if self.setting_value is None:
            return None
        if self.data_type == 'integer':
            return int(self.setting_value) if self.setting_value else 0
        elif self.data_type == 'number':
            return float(self.setting_value) if self.setting_value else 0.0
        elif self.data_type == 'boolean':
            return self.setting_value.lower() in ('true', '1', 'yes', 'on') if self.setting_value else False
        elif self.data_type == 'json':
            import json
            try:
                return json.loads(self.setting_value) if self.setting_value else {}
            except:
                return {}
        else:
            return self.setting_value
    
    def set_value(self, value):
        if value is None:
            self.setting_value = None
        elif self.data_type == 'integer':
            self.setting_value = str(int(value))
        elif self.data_type == 'number':
            self.setting_value = str(float(value))
        elif self.data_type == 'boolean':
            self.setting_value = 'true' if value in (True, 'true', '1', 'yes', 'on') else 'false'
        elif self.data_type == 'json':
            import json
            self.setting_value = json.dumps(value) if value else ''
        else:
            self.setting_value = str(value)
    
    def to_dict(self):
        return {
            'id': self.id,
            'key': self.setting_key,
            'value': self.get_value(),
            'data_type': self.data_type,
            'category': self.category,
            'description': self.description,
            'display_name': self.display_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    type = db.Column(db.String(50))          # 'device', 'location', 'cabinet'
    device_type = db.Column(db.String(50))   # 'router', 'switch', 'server' 等
    name = db.Column(db.String(200))         # 设备/位置/机柜名称
    action = db.Column(db.String(100))       # 操作描述
    status = db.Column(db.String(50))        # '成功', '失败', '警告'
    status_color = db.Column(db.String(20))  # 'success', 'danger', 'warning'
    user = db.Column(db.String(100))         # 操作人
    detail = db.Column(db.Text)              # 详情描述
# ==================== 文件末尾统一添加所有关系 ====================
# 注意：所有 relationship 必须在所有模型类定义之后添加，避免映射器初始化时找不到目标类

# Location 关系
Location.cabinets = db.relationship('Cabinet', back_populates='location', cascade='all, delete-orphan')
Location.location_devices = db.relationship('Device', back_populates='location')

# Cabinet 关系
Cabinet.location = db.relationship('Location', back_populates='cabinets')
Cabinet.devices = db.relationship('Device', back_populates='cabinet', cascade='all, delete-orphan')

# Device 关系
Device.cabinet = db.relationship('Cabinet', back_populates='devices')
Device.location = db.relationship('Location', back_populates='location_devices')
Device.interfaces = db.relationship('Interface', foreign_keys='Interface.device_id', backref='device_ref', cascade='all, delete-orphan')
Device.monitor_configs = db.relationship('DeviceMonitorConfig', back_populates='device', cascade='all, delete-orphan')
Device.performance_metrics = db.relationship(
    'PerformanceMetric', backref='device',
    # performance_metrics.device_id 为 NOT NULL：默认"解除关联"会置 NULL → 1048
    cascade='all, delete-orphan')
# Device.spare_parts 已注释，略

# Interface 关系
Interface.neighbor_device = db.relationship('Device', foreign_keys=[Interface.neighbor_device_id], backref='neighbor_interfaces')
Interface.interface_monitor_data = db.relationship('InterfaceMonitorData', back_populates='interface', cascade='all, delete-orphan')

# InventoryTransaction 关系
InventoryTransaction.device = db.relationship('Device', backref='inventory_transactions')

# InterfaceRelationship 关系
InterfaceRelationship.local_device = db.relationship('Device', foreign_keys=[InterfaceRelationship.local_device_id], backref='local_relationships')
InterfaceRelationship.remote_device = db.relationship('Device', foreign_keys=[InterfaceRelationship.remote_device_id], backref='remote_relationships')

# TopologyLog 关系
TopologyLog.device = db.relationship('Device', backref='topology_logs')
TopologyLog.relationship = db.relationship('InterfaceRelationship', backref='logs')

# DeviceMonitorLog 关系（原被注释，按需启用）
# DeviceMonitorLog.device = db.relationship('Device', backref='monitor_logs', lazy='joined')

# MonitorData 关系
MonitorData.device = db.relationship('Device', backref='monitor_data', lazy='joined')

# AlertEvent 关系
AlertEvent.rule = db.relationship('AlertRule', backref='alert_events', lazy='joined')
AlertEvent.device = db.relationship('Device', backref='alert_events', lazy='joined')

# InterfaceMonitorData 关系
InterfaceMonitorData.interface = db.relationship('Interface', back_populates='interface_monitor_data', lazy='joined')
InterfaceMonitorData.device = db.relationship('Device', backref='interface_monitor_data', lazy='joined')

# ConnectionPath 关系
ConnectionPath.source_device = db.relationship('Device', foreign_keys=[ConnectionPath.source_device_id], backref='source_connections')
ConnectionPath.target_device = db.relationship('Device', foreign_keys=[ConnectionPath.target_device_id], backref='target_connections')
ConnectionPath.source_interface = db.relationship('Interface', foreign_keys=[ConnectionPath.source_interface_id])
ConnectionPath.target_interface = db.relationship('Interface', foreign_keys=[ConnectionPath.target_interface_id])

# DeviceMonitorConfig 关系
DeviceMonitorConfig.device = db.relationship('Device', back_populates='monitor_configs')

# DiscoveryResult 关系
DiscoveryResult.task = db.relationship('DiscoveryTask', backref='results', lazy='joined')

# TopologyLayout 关系
TopologyLayout.topology = db.relationship('LogicalTopology', backref='layouts', lazy='joined')

# MonitorLog 关系
MonitorLog.monitor_schedule = db.relationship('MonitorSchedule', backref='monitor_logs')

# DeviceMonitor 关系
DeviceMonitor.device = db.relationship('Device', backref='monitor_status', uselist=False)

# Alert 关系
Alert.alert_event = db.relationship('AlertEvent', backref='alert_record', uselist=False)
Alert.device = db.relationship('Device', backref='alerts')
Alert.rule = db.relationship('AlertRule', backref='alerts')

# AlertAction 关系
AlertAction.notification_config = db.relationship('NotificationConfig', backref='alert_actions')

