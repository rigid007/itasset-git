"""软件许可管理模型"""
from datetime import datetime
from extensions import db


# 多对多: 许可与设备
license_devices = db.Table(
    'license_devices',
    db.Column('license_id', db.Integer, db.ForeignKey('software_licenses.id', ondelete='CASCADE'), primary_key=True),
    db.Column('device_id', db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), primary_key=True),
    db.Column('allocated_at', db.DateTime, default=datetime.utcnow),
    db.Column('allocated_by', db.Integer, db.ForeignKey('users.id')),
)


class SoftwareLicense(db.Model):
    """软件许可"""
    __tablename__ = 'software_licenses'

    id = db.Column(db.Integer, primary_key=True)
    license_key = db.Column(db.String(128), unique=True, comment='许可密钥')
    software_name = db.Column(db.String(200), nullable=False, index=True, comment='软件名称')
    version = db.Column(db.String(50), comment='版本号')
    edition = db.Column(db.String(50), comment='版本类型: Standard/Enterprise/Ultimate')
    license_type = db.Column(db.String(30), nullable=False, default='per_device',
                             comment='类型: per_user/per_device/enterprise/subscription')
    vendor = db.Column(db.String(100), comment='厂商')
    publisher = db.Column(db.String(100), comment='发布者')
    total_quantity = db.Column(db.Integer, default=1, comment='总数量')
    allocated_quantity = db.Column(db.Integer, default=0, comment='已分配数量')
    available_quantity = db.Column(db.Integer, default=0, comment='可用数量')
    purchase_date = db.Column(db.Date, comment='购买日期')
    expiry_date = db.Column(db.Date, comment='过期日期')
    renewal_date = db.Column(db.Date, comment='续约日期')
    purchase_cost = db.Column(db.Numeric(12, 2), default=0, comment='购买成本')
    unit_cost = db.Column(db.Numeric(12, 2), default=0, comment='单价')
    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), comment='关联合同')
    status = db.Column(db.String(20), default='active', comment='状态: active/expired/deprecated')
    compliance_status = db.Column(db.String(20), default='compliant',
                                  comment='合规: compliant/non-compliant/under-review')
    description = db.Column(db.Text, comment='备注')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    contract = db.relationship('Contract', backref='licenses', lazy='joined')
    devices = db.relationship('Device', secondary=license_devices,
                              backref=db.backref('licenses', lazy='dynamic'), lazy='subquery')

    def to_dict(self):
        return {
            'id': self.id,
            'license_key': self.license_key,
            'software_name': self.software_name,
            'version': self.version,
            'edition': self.edition,
            'license_type': self.license_type,
            'vendor': self.vendor,
            'total_quantity': self.total_quantity,
            'allocated_quantity': self.allocated_quantity,
            'available_quantity': self.available_quantity,
            'purchase_date': self.purchase_date.isoformat() if self.purchase_date else None,
            'expiry_date': self.expiry_date.isoformat() if self.expiry_date else None,
            'status': self.status,
            'compliance_status': self.compliance_status,
            'days_to_expiry': (self.expiry_date - datetime.utcnow().date()).days if self.expiry_date else None,
        }

    def update_quantities(self):
        """同步已分配与可用数量"""
        self.allocated_quantity = len(self.devices) if self.devices else 0
        self.available_quantity = max(0, self.total_quantity - self.allocated_quantity)

    def is_expiring_soon(self, days=30):
        if self.expiry_date:
            delta = self.expiry_date - datetime.utcnow().date()
            return 0 <= delta.days <= days
        return False
