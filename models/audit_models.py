"""资产盘点模型"""
from datetime import datetime
from extensions import db


class AssetAudit(db.Model):
    """资产盘点任务"""
    __tablename__ = 'asset_audits'

    id = db.Column(db.Integer, primary_key=True)
    audit_no = db.Column(db.String(64), unique=True, nullable=False, comment='盘点编号')
    name = db.Column(db.String(200), nullable=False, comment='盘点名称')
    audit_type = db.Column(db.String(20), default='annual', comment='类型: annual/quarterly/monthly/random')
    status = db.Column(db.String(20), default='draft', comment='状态: draft/in_progress/completed/cancelled')
    scope_location_ids = db.Column(db.Text, comment='盘点范围(位置ID列表JSON)')
    scope_department = db.Column(db.String(200), comment='盘点部门范围')
    scheduled_date = db.Column(db.Date, comment='计划日期')
    completed_date = db.Column(db.Date, comment='完成日期')
    total_assets = db.Column(db.Integer, default=0, comment='应盘资产总数')
    scanned_assets = db.Column(db.Integer, default=0, comment='已盘资产数')
    matched_count = db.Column(db.Integer, default=0, comment='一致数量')
    discrepancy_count = db.Column(db.Integer, default=0, comment='差异数量')
    missing_count = db.Column(db.Integer, default=0, comment='缺失数量')
    damaged_count = db.Column(db.Integer, default=0, comment='损坏数量')
    notes = db.Column(db.Text, comment='备注')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    items = db.relationship('AssetAuditItem', backref='audit', lazy='dynamic', cascade='all, delete-orphan')

    def progress_percent(self):
        if self.total_assets > 0:
            return round(self.scanned_assets / self.total_assets * 100, 1)
        return 0

    def to_dict(self):
        return {
            'id': self.id,
            'audit_no': self.audit_no,
            'name': self.name,
            'audit_type': self.audit_type,
            'status': self.status,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'completed_date': self.completed_date.isoformat() if self.completed_date else None,
            'total_assets': self.total_assets,
            'scanned_assets': self.scanned_assets,
            'matched_count': self.matched_count,
            'discrepancy_count': self.discrepancy_count,
            'missing_count': self.missing_count,
            'progress': self.progress_percent(),
        }


class AssetAuditItem(db.Model):
    """盘点明细"""
    __tablename__ = 'asset_audit_items'

    id = db.Column(db.Integer, primary_key=True)
    audit_id = db.Column(db.Integer, db.ForeignKey('asset_audits.id', ondelete='CASCADE'), nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id', ondelete='SET NULL'))
    asset_name = db.Column(db.String(200), comment='资产名称(冗余)')
    asset_number = db.Column(db.String(64), comment='资产编号(冗余)')
    expected_location = db.Column(db.String(200), comment='预期位置')
    actual_location = db.Column(db.String(200), comment='实际位置')
    expected_status = db.Column(db.String(20), comment='预期状态')
    actual_status = db.Column(db.String(20), comment='实际状态')
    scanned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    scanned_at = db.Column(db.DateTime, comment='盘点时间')
    status = db.Column(db.String(20), default='pending',
                       comment='结果: pending/matched/mismatched/missing/extra/damaged')
    notes = db.Column(db.Text, comment='备注')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
