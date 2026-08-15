from extensions import db
from datetime import datetime
import json

class ReportTemplate(db.Model):
    """报表模板"""
    __tablename__ = 'report_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    report_type = db.Column(db.String(50), nullable=False)  # device, alert, performance, etc.
    template_content = db.Column(db.Text)  # JSON格式的模板配置
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'report_type': self.report_type,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active
        }


class ScheduledReport(db.Model):
    """计划报表"""
    __tablename__ = 'scheduled_reports'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    report_type = db.Column(db.String(50), nullable=False)
    schedule_type = db.Column(db.String(20), nullable=False)  # daily, weekly, monthly, custom
    schedule_config = db.Column(db.Text)  # JSON格式的调度配置
    recipients = db.Column(db.Text)  # JSON格式的收件人列表
    format = db.Column(db.String(20), default='pdf')  # pdf, excel, html
    last_run_at = db.Column(db.DateTime)
    next_run_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'report_type': self.report_type,
            'schedule_type': self.schedule_type,
            'format': self.format,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'next_run_at': self.next_run_at.isoformat() if self.next_run_at else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ReportExecution(db.Model):
    """报表执行记录"""
    __tablename__ = 'report_executions'
    
    id = db.Column(db.Integer, primary_key=True)
    report_name = db.Column(db.String(100), nullable=False)
    report_type = db.Column(db.String(50), nullable=False)
    parameters = db.Column(db.Text)  # JSON格式的参数
    format = db.Column(db.String(20))
    file_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer)
    status = db.Column(db.String(20), default='pending')  # pending, running, completed, failed
    error_message = db.Column(db.Text)
    execution_time = db.Column(db.Integer)  # 执行时间（毫秒）
    generated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'report_name': self.report_name,
            'report_type': self.report_type,
            'format': self.format,
            'file_size': self.file_size,
            'status': self.status,
            'execution_time': self.execution_time,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None
        }


class ReportFavorite(db.Model):
    """报表收藏"""
    __tablename__ = 'report_favorites'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    report_type = db.Column(db.String(50), nullable=False)
    report_name = db.Column(db.String(100), nullable=False)
    parameters = db.Column(db.Text)  # JSON格式的参数配置
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'report_type': self.report_type,
            'report_name': self.report_name,
            'sort_order': self.sort_order
        }


class ReportDashboard(db.Model):
    """报表仪表板"""
    __tablename__ = 'report_dashboards'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, comment='仪表板名称')
    description = db.Column(db.Text, comment='描述')
    dashboard_type = db.Column(db.String(30), default='operational', comment='类型: executive/operational/compliance')
    layout_config = db.Column(db.Text, comment='布局配置JSON')
    widgets = db.Column(db.Text, comment='组件配置JSON')
    role_access = db.Column(db.String(50), default='all', comment='角色访问权限')
    is_default = db.Column(db.Boolean, default=False, comment='是否默认')
    is_shared = db.Column(db.Boolean, default=False, comment='是否共享')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'dashboard_type': self.dashboard_type,
            'is_default': self.is_default,
            'is_shared': self.is_shared,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ReportDistribution(db.Model):
    """报表分发"""
    __tablename__ = 'report_distributions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, comment='分发任务名称')
    report_type = db.Column(db.String(50), nullable=False, comment='报表类型')
    schedule_cron = db.Column(db.String(100), comment='Cron表达式')
    format = db.Column(db.String(20), default='pdf', comment='格式: pdf/excel/html')
    delivery_channel = db.Column(db.String(30), default='email', comment='渠道: email/slack/webhook')
    recipients = db.Column(db.Text, comment='收件人JSON')
    last_sent_at = db.Column(db.DateTime, comment='上次发送')
    next_send_at = db.Column(db.DateTime, comment='下次发送')
    enabled = db.Column(db.Boolean, default=True)
    retry_on_fail = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'report_type': self.report_type,
            'format': self.format,
            'delivery_channel': self.delivery_channel,
            'enabled': self.enabled,
            'last_sent_at': self.last_sent_at.isoformat() if self.last_sent_at else None,
            'next_send_at': self.next_send_at.isoformat() if self.next_send_at else None,
        }


class ComplianceFramework(db.Model):
    """合规框架"""
    __tablename__ = 'compliance_frameworks'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, comment='框架名称')
    version = db.Column(db.String(20), comment='版本')
    description = db.Column(db.Text, comment='描述')
    control_items = db.Column(db.Text, comment='控制项JSON')
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ComplianceEvidence(db.Model):
    """合规证据"""
    __tablename__ = 'compliance_evidences'

    id = db.Column(db.Integer, primary_key=True)
    framework_id = db.Column(db.Integer, db.ForeignKey('compliance_frameworks.id'), nullable=False)
    control_id = db.Column(db.String(50), nullable=False, comment='控制项ID')
    evidence_type = db.Column(db.String(20), default='manual', comment='类型: manual/automated')
    content = db.Column(db.Text, comment='证据内容')
    collected_at = db.Column(db.DateTime, default=datetime.utcnow, comment='收集时间')
    collected_by = db.Column(db.Integer, db.ForeignKey('users.id'), comment='收集人')
    status = db.Column(db.String(20), default='pending', comment='状态: pass/fail/na/pending')

    framework = db.relationship('ComplianceFramework', backref='evidences')

    def to_dict(self):
        return {
            'id': self.id,
            'framework_id': self.framework_id,
            'control_id': self.control_id,
            'evidence_type': self.evidence_type,
            'status': self.status,
            'collected_at': self.collected_at.isoformat() if self.collected_at else None,
        }

