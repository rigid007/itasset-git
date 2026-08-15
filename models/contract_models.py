"""合同管理模型 - Contract & Related"""
from datetime import datetime
from extensions import db


# 多对多关联表：合同与资产
contract_assets = db.Table(
    'contract_assets',
    db.Column('contract_id', db.Integer, db.ForeignKey('contracts.id', ondelete='CASCADE'), primary_key=True),
    db.Column('asset_id', db.Integer, db.ForeignKey('assets.id', ondelete='CASCADE'), primary_key=True),
    db.Column('created_at', db.DateTime, default=datetime.utcnow)
)


class Contract(db.Model):
    """合同"""
    __tablename__ = 'contracts'

    id = db.Column(db.Integer, primary_key=True)
    contract_no = db.Column(db.String(64), unique=True, nullable=False, index=True, comment='合同编号')
    name = db.Column(db.String(200), nullable=False, comment='合同名称')
    contract_type = db.Column(db.String(30), nullable=False, default='purchase',
                               comment='类型: purchase采购/maintenance维护/lease租赁/sla服务协议')
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), comment='供应商')
    start_date = db.Column(db.Date, nullable=False, comment='开始日期')
    end_date = db.Column(db.Date, nullable=False, comment='结束日期')
    renewal_date = db.Column(db.Date, comment='续约日期')
    total_value = db.Column(db.Numeric(12, 2), default=0, comment='合同总金额')
    payment_terms = db.Column(db.String(200), comment='付款条款')
    payment_status = db.Column(db.String(20), default='pending', comment='付款状态: pending/partial/paid')
    attachment_url = db.Column(db.String(500), comment='附件路径')
    description = db.Column(db.Text, comment='描述备注')
    status = db.Column(db.String(20), default='active', comment='状态: active/expired/terminated/renewed')
    notification_days = db.Column(db.Integer, default=30, comment='到期提前提醒天数')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    supplier = db.relationship('Supplier', backref='contracts')
    assets = db.relationship('Asset', secondary=contract_assets, backref=db.backref('contracts', lazy='dynamic'),
                             lazy='subquery')

    def to_dict(self):
        return {
            'id': self.id,
            'contract_no': self.contract_no,
            'name': self.name,
            'contract_type': self.contract_type,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier.name if self.supplier else '',
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'renewal_date': self.renewal_date.isoformat() if self.renewal_date else None,
            'total_value': float(self.total_value) if self.total_value else 0,
            'payment_status': self.payment_status,
            'status': self.status,
            'notification_days': self.notification_days,
            'description': self.description,
            'days_remaining': (self.end_date - datetime.utcnow().date()).days if self.end_date else None,
        }

    def days_remaining(self):
        if self.end_date:
            delta = self.end_date - datetime.utcnow().date()
            return delta.days
        return None

    def is_expiring_soon(self):
        dr = self.days_remaining()
        if dr is not None and self.notification_days:
            return 0 <= dr <= self.notification_days
        return False
