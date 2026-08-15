from __future__ import annotations
from datetime import datetime, timezone
from extensions import db

# 多对多关联表：设备分组 <-> 设备
device_group_members = db.Table(
    'device_group_members',
    db.Column('device_id', db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('device_groups.id', ondelete='CASCADE'), primary_key=True),
    db.Column('assigned_at', db.DateTime, default=lambda: datetime.now(timezone.utc))
)


class DeviceGroup(db.Model):
    __tablename__ = 'device_groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    description = db.Column(db.Text)
    color = db.Column(db.String(20), default='#007bff')
    icon = db.Column(db.String(50), default='fa-folder')
    sort_order = db.Column(db.Integer, default=0)

    # 树形层级：自引用
    parent_id = db.Column(db.Integer, db.ForeignKey('device_groups.id', ondelete='SET NULL'), nullable=True)
    children = db.relationship('DeviceGroup', backref=db.backref('parent', remote_side=[id]),
                               lazy='select', order_by='DeviceGroup.sort_order')

    # 自动归类规则
    auto_rule_type = db.Column(db.String(20), nullable=True)  # None=人工, ip_subnet, name_pattern
    auto_rule_value = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # 多对多关系
    devices = db.relationship('Device', secondary=device_group_members,
                              backref=db.backref('groups', lazy='select'),
                              lazy='select', order_by='Device.name')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'color': self.color,
            'icon': self.icon,
            'sort_order': self.sort_order,
            'parent_id': self.parent_id,
            'auto_rule_type': self.auto_rule_type,
            'auto_rule_value': self.auto_rule_value or '',
            'device_count': len(self.devices) if self.devices else 0,
            'created_at': self.created_at.isoformat() if self.created_at else '',
        }

    def __repr__(self):
        return f'<DeviceGroup {self.name}>'
