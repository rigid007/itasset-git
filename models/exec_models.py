# -*- coding: utf-8 -*-
"""自动化执行中心模型：批量执行任务 / 每设备结果 / 作业模板 / API 令牌。"""
import hashlib
import secrets
from extensions import db
from models._base import utcnow as _utcnow


class ExecTemplate(db.Model):
    """作业模板：可复用的命令/脚本集合"""
    __tablename__ = 'exec_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    task_type = db.Column(db.String(20), default='command')   # command / script / config_push
    protocol = db.Column(db.String(20), default='auto')       # auto / ssh / winrm / netmiko / local
    content = db.Column(db.Text, nullable=False)
    timeout = db.Column(db.Integer, default=30)
    approval_required = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f'<ExecTemplate {self.name}>'


class ExecTask(db.Model):
    """批量执行任务"""
    __tablename__ = 'exec_tasks'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    description = db.Column(db.Text)
    task_type = db.Column(db.String(20), default='command')   # command / script / config_push
    protocol = db.Column(db.String(20), default='auto')
    content = db.Column(db.Text, nullable=False)
    timeout = db.Column(db.Integer, default=30)

    # 目标范围（便于追溯，实际目标以 task_devices 为准）
    target_scope = db.Column(db.String(20), default='devices')  # devices / group / subnet / all
    target_ref = db.Column(db.String(200), default='')

    # 状态机：ready / waiting_approval / running / completed / partial / failed / cancelled / rejected
    status = db.Column(db.String(20), default='ready', index=True)
    approval_required = db.Column(db.Boolean, default=False)
    approval_status = db.Column(db.String(20), default='none')  # none / pending / approved / rejected
    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approval_comment = db.Column(db.String(500))
    approved_at = db.Column(db.DateTime)

    # 定时
    schedule_enabled = db.Column(db.Boolean, default=False)
    schedule_type = db.Column(db.String(20), default='interval')  # once / interval / cron
    schedule_value = db.Column(db.String(100), default='')        # 如 5m / 0 3 * * *
    next_run_at = db.Column(db.DateTime)
    last_run_at = db.Column(db.DateTime)

    notify_enabled = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by_user = db.relationship(
        'User', foreign_keys=[created_by], lazy='select',
        backref=db.backref('exec_tasks', lazy='dynamic'),
    )
    created_at = db.Column(db.DateTime, default=_utcnow)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)

    device_count = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    result_summary = db.Column(db.Text)

    devices = db.relationship(
        'ExecTaskDevice', backref='task', lazy='dynamic',
        cascade='all, delete-orphan', order_by='ExecTaskDevice.id',
    )

    def __repr__(self):
        return f'<ExecTask {self.name} [{self.status}]>'

    @property
    def creator(self):
        return self.created_by_user.username if self.created_by_user else ''

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'task_type': self.task_type,
            'protocol': self.protocol,
            'status': self.status,
            'approval_status': self.approval_status,
            'device_count': self.device_count,
            'success_count': self.success_count,
            'failed_count': self.failed_count,
            'schedule_enabled': self.schedule_enabled,
            'created_by': self.creator,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'finished_at': self.finished_at.strftime('%Y-%m-%d %H:%M:%S') if self.finished_at else '',
        }


class ExecTaskDevice(db.Model):
    """任务在单台设备上的执行结果"""
    __tablename__ = 'exec_task_devices'
    __table_args__ = (
        db.UniqueConstraint('task_id', 'device_id', name='uq_exec_task_device'),
    )

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('exec_tasks.id'), nullable=False, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    device_name = db.Column(db.String(128), default='')
    ip_address = db.Column(db.String(45), default='')
    protocol = db.Column(db.String(20), default='auto')
    status = db.Column(db.String(20), default='pending', index=True)  # pending/running/success/failed/cancelled/skipped
    output = db.Column(db.Text)
    error = db.Column(db.Text)
    snapshot_config = db.Column(db.Text)   # config_push 执行前的配置快照（回滚用）
    exit_code = db.Column(db.Integer)
    duration = db.Column(db.Float)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)

    device = db.relationship('Device', backref='exec_results', lazy='select')

    def __repr__(self):
        return f'<ExecTaskDevice task={self.task_id} device={self.device_id} [{self.status}]>'

    def to_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'device_id': self.device_id,
            'device_name': self.device_name or (self.device.name if self.device else ''),
            'ip_address': self.ip_address,
            'protocol': self.protocol,
            'status': self.status,
            'output': (self.output or '')[:2000],
            'error': self.error or '',
            'exit_code': self.exit_code,
            'duration': self.duration,
        }


class ApiKey(db.Model):
    """对外 API 令牌"""
    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    key_prefix = db.Column(db.String(16), default='')
    key_hash = db.Column(db.String(64), unique=True, nullable=False)
    scope = db.Column(db.String(20), default='read')   # read / write
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    last_used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=_utcnow)

    def __repr__(self):
        return f'<ApiKey {self.name}>'

    @staticmethod
    def generate_key():
        return 'api_' + secrets.token_urlsafe(32)

    @staticmethod
    def hash_key(key):
        return hashlib.sha256(key.encode()).hexdigest()
