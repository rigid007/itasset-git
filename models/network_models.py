# -*- coding: utf-8 -*-
"""网络管理（IPAM）模型：VLAN / 子网 / IP 地址。"""
from extensions import db
from models._base import utcnow as _utcnow


class Vlan(db.Model):
    """VLAN 管理"""
    __tablename__ = 'vlans'

    id = db.Column(db.Integer, primary_key=True)
    vlan_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    name = db.Column(db.String(128), nullable=False)
    vlan_type = db.Column(db.String(32), default='业务')  # 业务/管理/互联/无线...
    gateway = db.Column(db.String(45))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='active', index=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    subnets = db.relationship('Subnet', backref='vlan', lazy='dynamic')

    def __repr__(self):
        return f'<Vlan {self.vlan_id} {self.name}>'

    def subnet_count(self):
        return self.subnets.count() if self.subnets else 0

    def to_dict(self):
        return {
            'id': self.id,
            'vlan_id': self.vlan_id,
            'name': self.name,
            'vlan_type': self.vlan_type or '',
            'gateway': self.gateway or '',
            'description': self.description or '',
            'status': self.status or 'active',
            'subnet_count': self.subnet_count(),
        }


class Subnet(db.Model):
    """子网管理"""
    __tablename__ = 'subnets'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    network = db.Column(db.String(45), nullable=False)       # 网络地址，如 192.168.1.0
    prefix_length = db.Column(db.Integer, nullable=False)    # 前缀长度，如 24
    gateway = db.Column(db.String(45))
    vlan_id = db.Column(db.Integer, db.ForeignKey('vlans.id'), nullable=True, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True, index=True)
    department = db.Column(db.String(100))
    tags = db.Column(db.String(255))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='active', index=True)
    ipam_enabled = db.Column(db.Boolean, default=True)       # 是否纳入 IP 地址管理
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    location = db.relationship('Location', backref='subnets', lazy='select')

    ip_addresses = db.relationship(
        'IPAddress', backref='subnet', lazy='dynamic',
        cascade='all, delete-orphan',
    )

    def __repr__(self):
        return f'<Subnet {self.cidr}>'

    @property
    def cidr(self):
        return f'{self.network}/{self.prefix_length}'

    @property
    def netmask(self):
        try:
            import ipaddress as ipmod
            return str(ipmod.IPv4Network(self.cidr, strict=False).netmask)
        except Exception:
            return ''

    @property
    def broadcast(self):
        try:
            import ipaddress as ipmod
            return str(ipmod.IPv4Network(self.cidr, strict=False).broadcast_address)
        except Exception:
            return ''

    @property
    def total_hosts(self):
        try:
            import ipaddress as ipmod
            return ipmod.IPv4Network(self.cidr, strict=False).num_addresses
        except Exception:
            return 0

    @property
    def usable_hosts(self):
        """可用主机数（不含网络地址与广播地址）。"""
        total = self.total_hosts
        return max(total - 2, 0) if total >= 2 else total

    def _ip_counts(self):
        status_map = {'available': 0, 'reserved': 0, 'allocated': 0, 'disabled': 0}
        for ip in self.ip_addresses:
            key = ip.status if ip.status in status_map else 'available'
            status_map[key] += 1
        return status_map

    @property
    def ip_usage(self):
        counts = self._ip_counts()
        tracked = sum(counts.values())
        return {
            'total': tracked,
            'available': counts['available'],
            'reserved': counts['reserved'],
            'allocated': counts['allocated'],
            'disabled': counts['disabled'],
            'usage_percent': round(counts['allocated'] / tracked * 100, 1) if tracked else 0,
            'free_percent': round((counts['available'] + counts['reserved']) / tracked * 100, 1) if tracked else 0,
        }

    @property
    def location_name(self):
        return self.location.name if self.location else ''

    def to_dict(self):
        usage = self.ip_usage
        return {
            'id': self.id,
            'name': self.name,
            'cidr': self.cidr,
            'network': self.network,
            'prefix_length': self.prefix_length,
            'netmask': self.netmask,
            'broadcast': self.broadcast,
            'gateway': self.gateway or '',
            'vlan_id': self.vlan_id,
            'vlan_name': self.vlan.name if self.vlan else '',
            'location_id': self.location_id,
            'location_name': self.location_name,
            'department': self.department or '',
            'description': self.description or '',
            'status': self.status or 'active',
            'ipam_enabled': self.ipam_enabled,
            'total_hosts': self.total_hosts,
            'usable_hosts': self.usable_hosts,
            'ip_usage': usage,
        }


class IPAddress(db.Model):
    """IP 地址管理（IPAM）"""
    __tablename__ = 'ip_addresses'
    __table_args__ = (
        db.UniqueConstraint('subnet_id', 'ip_address', name='uq_subnet_ip'),
        db.Index('idx_ip_status', 'status'),
        db.Index('idx_ip_device', 'device_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    subnet_id = db.Column(db.Integer, db.ForeignKey('subnets.id'), nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=False, index=True)
    status = db.Column(db.String(20), default='available', index=True)  # available/reserved/allocated/disabled
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True)
    hostname = db.Column(db.String(128))
    mac_address = db.Column(db.String(17))
    owner = db.Column(db.String(64))       # 使用人/申请人
    department = db.Column(db.String(100))
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    device = db.relationship('Device', backref='managed_ips', lazy='select')

    def __repr__(self):
        return f'<IPAddress {self.ip_address} [{self.status}]>'

    def to_dict(self):
        return {
            'id': self.id,
            'subnet_id': self.subnet_id,
            'subnet_cidr': self.subnet.cidr if self.subnet else '',
            'ip_address': self.ip_address,
            'status': self.status or 'available',
            'device_id': self.device_id,
            'device_name': self.device.name if self.device else '',
            'hostname': self.hostname or '',
            'mac_address': self.mac_address or '',
            'owner': self.owner or '',
            'department': self.department or '',
            'description': self.description or '',
            'vlan_id': self.subnet.vlan_id if self.subnet else None,
            'vlan_name': self.subnet.vlan.name if self.subnet and self.subnet.vlan else '',
        }
