from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON, Text
import json
from extensions import db  # 改为使用统一的 db 实例
from models.models import AlertRule
from sqlalchemy import Column, Integer, ForeignKey




class MetricData(db.Model):
    __tablename__ = 'metric_data'
    id = db.Column(db.Integer, primary_key=True)
    device_config_id = db.Column(db.Integer, db.ForeignKey('device_config.id'))
    metric_name = db.Column(db.String(64))   # ping_loss_rate, ping_avg_rtt, cpu_usage, memory_usage, temperature, power_supply
    value = db.Column(db.Float)
    collected_at = db.Column(db.DateTime, default=datetime.utcnow)

# class AlertRule(db.Model):
#     __tablename__ = 'alert_rule'
#     id = db.Column(db.Integer, primary_key=True)
#     device_config_id = db.Column(db.Integer, db.ForeignKey('device_config.id'))
#     metric_name = db.Column(db.String(64))   # 对应 MetricData.metric_name
#     operator = db.Column(db.String(8))       # >, <, >=, <=, ==
#     threshold = db.Column(db.Float)
#     duration = db.Column(db.Integer, default=60)  # 持续秒数
#     enabled = db.Column(db.Boolean, default=True)
#     notify_channels = db.Column(db.JSON)     # ["email", "dingtalk"]
#     notify_targets = db.Column(db.JSON)      # ["admin@example.com"] 或 webhook url
#     last_alert_at = db.Column(db.DateTime)
#     description = db.Column(db.String(256))

class AlertHistory(db.Model):
    __tablename__ = 'alert_history'

    id = db.Column(db.Integer, primary_key=True)

    rule_id = db.Column(
        db.Integer,
        db.ForeignKey("rule.id"),
        nullable=False
    )

    device_config_id = db.Column(
        db.Integer,
        db.ForeignKey("device_config.id")
    )

    metric_name = db.Column(db.String(64))
    current_value = db.Column(db.Float)
    threshold = db.Column(db.Float)
    operator = db.Column(db.String(8))
    message = db.Column(db.String(512))

    triggered_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
    status = db.Column(db.String(16), default='firing')

    # relationships
    rule = db.relationship(
        "Rule",
        back_populates="alert_histories"
    )

    device_config = db.relationship(
        "DeviceConfig",
        backref="alert_histories"
    )




# models.py
class DeviceConfig(db.Model):
    __tablename__ = 'device_config'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), unique=True, nullable=False)
    device = db.relationship('Device', backref=db.backref('monitor_config', uselist=False, cascade='all, delete-orphan'))

    # 全局开关
    enabled = db.Column(db.Boolean, default=True)

    # Ping 配置
    enable_ping = db.Column(db.Boolean, default=True)
    ping_interval = db.Column(db.Integer, default=30)
    ping_timeout = db.Column(db.Float, default=2.0)

    # SNMP 配置
    enable_snmp = db.Column(db.Boolean, default=False)
    snmp_version = db.Column(db.String(8), default='2c')
    snmp_community = db.Column(db.String(64), default='public')
    snmp_interval = db.Column(db.Integer, default=300)
    snmp_timeout = db.Column(db.Float, default=3.0)
    # SNMP v3
    snmp_username = db.Column(db.String(64))
    snmp_auth_password = db.Column(db.String(128))
    snmp_priv_password = db.Column(db.String(128))
    snmp_auth_protocol = db.Column(db.String(8))
    snmp_priv_protocol = db.Column(db.String(8))

    # SSH 配置
    enable_ssh = db.Column(db.String(8), default='no')   # 'yes', 'no', 'auto'
    ssh_username = db.Column(db.String(64))
    ssh_password = db.Column(db.String(256))
    ssh_port = db.Column(db.Integer, default=22)
    ssh_key_file = db.Column(db.String(256))
    ssh_interval = db.Column(db.Integer, default=600)
    ssh_timeout = db.Column(db.Float, default=5.0)

    # API 配置
    enable_api = db.Column(db.Boolean, default=False)
    api_url = db.Column(db.String(512))
    api_method = db.Column(db.String(16), default='GET')
    api_auth_type = db.Column(db.String(16))
    api_auth_value = db.Column(db.String(256))
    api_headers = db.Column(db.Text)
    api_body = db.Column(db.Text)
    api_interval = db.Column(db.Integer, default=600)
    api_timeout = db.Column(db.Float, default=10.0)

    # 通用重试
    retry_count = db.Column(db.Integer, default=1)
    retry_interval = db.Column(db.Integer, default=1)

    # 监控指标配置
    monitor_metrics = db.Column(db.Text)
    inherit_alerts = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_api_headers(self):
        try:
            return json.loads(self.api_headers) if self.api_headers else {}
        except:
            return {}

    def set_api_headers(self, headers_dict):
        self.api_headers = json.dumps(headers_dict) if headers_dict else None

    def get_monitor_metrics(self):
        try:
            return json.loads(self.monitor_metrics) if self.monitor_metrics else {}
        except:
            return {}
class Rule(db.Model):
    __tablename__ = "rule"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128))

    alert_histories = db.relationship(
        "AlertHistory",
        back_populates="rule",
        cascade="all, delete-orphan"
    )


class DeviceHealthScore(db.Model):
    """设备健康评分"""
    __tablename__ = 'device_health_scores'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False, index=True)
    score = db.Column(db.Integer, default=100, comment='综合评分 0-100')
    cpu_score = db.Column(db.Integer, default=100)
    memory_score = db.Column(db.Integer, default=100)
    disk_score = db.Column(db.Integer, default=100)
    network_score = db.Column(db.Integer, default=100)
    ping_score = db.Column(db.Integer, default=100)
    components = db.Column(db.Text, comment='各组件详情JSON')
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow, comment='计算时间')
    device = db.relationship('Device', backref='health_scores')

    def to_dict(self):
        return {
            'device_id': self.device_id,
            'score': self.score,
            'cpu_score': self.cpu_score,
            'memory_score': self.memory_score,
            'disk_score': self.disk_score,
            'network_score': self.network_score,
            'ping_score': self.ping_score,
            'calculated_at': self.calculated_at.isoformat() if self.calculated_at else None,
        }


class MaintenanceWindow(db.Model):
    """维护窗口"""
    __tablename__ = 'maintenance_windows'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, comment='窗口名称')
    description = db.Column(db.Text, comment='描述')
    start_time = db.Column(db.DateTime, nullable=False, comment='开始时间')
    end_time = db.Column(db.DateTime, nullable=False, comment='结束时间')
    affected_device_ids = db.Column(db.Text, comment='受影响设备ID列表JSON')
    reason = db.Column(db.String(500), comment='维护原因')
    status = db.Column(db.String(20), default='scheduled', comment='状态: scheduled/active/completed/cancelled')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlertEscalationPolicy(db.Model):
    """告警升级策略"""
    __tablename__ = 'alert_escalation_policies'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, comment='策略名称')
    alert_rule_id = db.Column(db.Integer, db.ForeignKey('alert_rules.id', ondelete='SET NULL'))
    escalation_level = db.Column(db.Integer, default=1, comment='升级级别 1/2/3')
    wait_minutes = db.Column(db.Integer, default=15, comment='等待时间(分钟)')
    notify_channel = db.Column(db.String(50), comment='通知渠道: email/sms/webhook/dingtalk')
    notify_target = db.Column(db.String(500), comment='通知目标: 邮箱地址/URL/手机号')
    notify_template = db.Column(db.Text, comment='通知模板')
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SlaUptime(db.Model):
    """SLA在线率"""
    __tablename__ = 'sla_uptimes'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False)
    period = db.Column(db.String(20), nullable=False, comment='周期: monthly/quarterly/yearly')
    uptime_percentage = db.Column(db.Float, default=100.0, comment='在线率百分比')
    total_minutes = db.Column(db.Integer, default=0, comment='总分钟数')
    downtime_minutes = db.Column(db.Integer, default=0, comment='宕机分钟数')
    period_start = db.Column(db.DateTime, comment='周期开始')
    period_end = db.Column(db.DateTime, comment='周期结束')
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow)
    device = db.relationship('Device', backref='sla_records')

    __table_args__ = (
        db.UniqueConstraint('device_id', 'period_start', 'period', name='uq_sla_period'),
    )


class AnomalyDetectionRule(db.Model):
    """异常检测规则"""
    __tablename__ = 'anomaly_detection_rules'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), nullable=True)
    metric_name = db.Column(db.String(50), nullable=False, comment='指标: cpu/memory/disk/network/temperature')
    method = db.Column(db.String(50), default='statistical_deviation', comment='方法: statistical_deviation/moving_average')
    sensitivity = db.Column(db.String(20), default='medium', comment='灵敏度: high/medium/low')
    baseline_period_days = db.Column(db.Integer, default=30, comment='基线周期(天)')
    deviation_threshold = db.Column(db.Float, default=2.0, comment='标准差倍数阈值')
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AutomatedRemediation(db.Model):
    """自动修复规则"""
    __tablename__ = 'automated_remediations'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, comment='规则名称')
    trigger_alert_rule_id = db.Column(db.Integer, db.ForeignKey('alert_rules.id', ondelete='SET NULL'))
    action_type = db.Column(db.String(30), nullable=False, comment='动作: ssh_command/api_call/webhook/restart_service')
    action_params = db.Column(db.Text, comment='动作参数JSON')
    target_device_type = db.Column(db.String(50), comment='目标设备类型')
    enabled = db.Column(db.Boolean, default=True)
    success_count = db.Column(db.Integer, default=0)
    fail_count = db.Column(db.Integer, default=0)
    last_executed_at = db.Column(db.DateTime)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)