from datetime import datetime, timedelta, timezone
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON, Text
import json
from extensions import db  # 改为使用统一的 db 实例
from utils.security import CredentialEncryptor

class SystemSetting(db.Model):
    """系统设置模型"""
    __tablename__ = 'system_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=False)
    data_type = db.Column(db.String(20), default='string')  # string, integer, boolean, json, array
    category = db.Column(db.String(50), nullable=False, default='general')  # general, email, security, performance, ui
    display_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    options = db.Column(db.Text)  # JSON格式的选项列表
    is_encrypted = db.Column(db.Boolean, default=False)
    is_required = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'value': self.value,
            'data_type': self.data_type,
            'category': self.category,
            'display_name': self.display_name,
            'description': self.description,
            'is_encrypted': self.is_encrypted,
            'is_required': self.is_required,
            'sort_order': self.sort_order
        }

class GlobalParameter(db.Model):
    """全局参数模型"""
    __tablename__ = 'global_parameters'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    value = db.Column(db.Text, nullable=False)
    data_type = db.Column(db.String(20), default='string')
    category = db.Column(db.String(50), default='general')
    description = db.Column(db.Text)
    default_value = db.Column(db.Text)
    min_value = db.Column(db.String(50))
    max_value = db.Column(db.String(50))
    unit = db.Column(db.String(20))
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'value': self.value,
            'data_type': self.data_type,
            'category': self.category,
            'description': self.description,
            'default_value': self.default_value,
            'min_value': self.min_value,
            'max_value': self.max_value,
            'unit': self.unit,
            'enabled': self.enabled
        }

class BackupConfig(db.Model):
    """备份配置模型"""
    __tablename__ = 'backup_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    backup_type = db.Column(db.String(20), nullable=False)  # full, incremental, differential
    schedule_type = db.Column(db.String(20), default='daily')  # daily, weekly, monthly, manual
    schedule_config = db.Column(db.Text)  # JSON格式的调度配置
    retention_days = db.Column(db.Integer, default=30)
    include_database = db.Column(db.Boolean, default=True)
    include_files = db.Column(db.Boolean, default=False)
    include_logs = db.Column(db.Boolean, default=False)
    storage_path = db.Column(db.String(500))
    storage_type = db.Column(db.String(20), default='local')  # local, ftp, s3
    storage_config = db.Column(db.Text)  # JSON格式的存储配置
    enabled = db.Column(db.Boolean, default=True)
    last_backup_at = db.Column(db.DateTime)
    last_backup_status = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'backup_type': self.backup_type,
            'schedule_type': self.schedule_type,
            'schedule_config': json.loads(self.schedule_config) if self.schedule_config else {},
            'retention_days': self.retention_days,
            'include_database': self.include_database,
            'include_files': self.include_files,
            'include_logs': self.include_logs,
            'storage_path': self.storage_path,
            'storage_type': self.storage_type,
            'storage_config': json.loads(self.storage_config) if self.storage_config else {},
            'enabled': self.enabled,
            'last_backup_at': self.last_backup_at.isoformat() if self.last_backup_at else None,
            'last_backup_status': self.last_backup_status
        }

class MonitoringTemplate(db.Model):
    """监控模板模型"""
    __tablename__ = 'monitoring_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    device_type = db.Column(db.String(50))  # 设备类型
    vendor = db.Column(db.String(100))  # 厂商
    model = db.Column(db.String(100))  # 型号
    monitoring_items = db.Column(db.Text)  # JSON格式的监控项配置
    threshold_config = db.Column(db.Text)  # JSON格式的阈值配置
    polling_interval = db.Column(db.Integer, default=300)  # 轮询间隔（秒）
    timeout = db.Column(db.Integer, default=30)  # 超时时间（秒）
    enabled = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'device_type': self.device_type,
            'vendor': self.vendor,
            'model': self.model,
            'monitoring_items': json.loads(self.monitoring_items) if self.monitoring_items else [],
            'threshold_config': json.loads(self.threshold_config) if self.threshold_config else {},
            'polling_interval': self.polling_interval,
            'timeout': self.timeout,
            'enabled': self.enabled,
            'is_default': self.is_default
        }

class CollectionSetting(db.Model):
    """采集设置模型"""
    __tablename__ = 'collection_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    collection_type = db.Column(db.String(50), nullable=False)  # snmp, telnet, ssh, api, ping
    protocol = db.Column(db.String(20))  # udp, tcp
    port = db.Column(db.Integer)
    timeout = db.Column(db.Integer, default=30)
    retries = db.Column(db.Integer, default=3)
    polling_interval = db.Column(db.Integer, default=300)
    bulk_collection = db.Column(db.Boolean, default=False)
    max_concurrent = db.Column(db.Integer, default=10)
    data_retention_days = db.Column(db.Integer, default=30)
    compression_enabled = db.Column(db.Boolean, default=True)
    enabled = db.Column(db.Boolean, default=True)
    config = db.Column(db.Text)  # JSON格式的采集配置
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'collection_type': self.collection_type,
            'protocol': self.protocol,
            'port': self.port,
            'timeout': self.timeout,
            'retries': self.retries,
            'polling_interval': self.polling_interval,
            'bulk_collection': self.bulk_collection,
            'max_concurrent': self.max_concurrent,
            'data_retention_days': self.data_retention_days,
            'compression_enabled': self.compression_enabled,
            'enabled': self.enabled,
            'config': json.loads(self.config) if self.config else {}
        }

class ThresholdProfile(db.Model):
    """阈值配置模型"""
    __tablename__ = 'threshold_profiles'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    metric_type = db.Column(db.String(50), nullable=False)  # cpu, memory, disk, network, temperature
    warning_threshold = db.Column(db.Float)
    critical_threshold = db.Column(db.Float)
    recovery_threshold = db.Column(db.Float)
    duration = db.Column(db.Integer, default=300)  # 持续时间（秒）
    condition_type = db.Column(db.String(20), default='greater')  # greater, less, equal, not_equal
    unit = db.Column(db.String(20))
    enabled = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    apply_to_all = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'metric_type': self.metric_type,
            'warning_threshold': self.warning_threshold,
            'critical_threshold': self.critical_threshold,
            'recovery_threshold': self.recovery_threshold,
            'duration': self.duration,
            'condition_type': self.condition_type,
            'unit': self.unit,
            'enabled': self.enabled,
            'is_default': self.is_default,
            'apply_to_all': self.apply_to_all
        }

class AlertConfigTemplate(db.Model):
    #告警模板模型
    __tablename__ = 'alert_config_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    severity = db.Column(db.String(20), default='warning')  # critical, error, warning, info
    alert_type = db.Column(db.String(50), nullable=False)  # performance, availability, configuration, security
    match_conditions = db.Column(db.Text)  # JSON格式的匹配条件
    notification_channels = db.Column(db.Text)  # JSON格式的通知通道配置
    actions = db.Column(db.Text)  # JSON格式的告警动作
    auto_acknowledge = db.Column(db.Boolean, default=False)
    auto_resolve = db.Column(db.Boolean, default=False)
    enabled = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'severity': self.severity,
            'alert_type': self.alert_type,
            'match_conditions': json.loads(self.match_conditions) if self.match_conditions else [],
            'notification_channels': json.loads(self.notification_channels) if self.notification_channels else [],
            'actions': json.loads(self.actions) if self.actions else [],
            'auto_acknowledge': self.auto_acknowledge,
            'auto_resolve': self.auto_resolve,
            'enabled': self.enabled,
            'is_default': self.is_default
        }

class NotificationTemplate(db.Model):
    """通知模板模型"""
    __tablename__ = 'notification_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    notification_type = db.Column(db.String(20), nullable=False)  # email, sms, webhook, slack, wechat
    template_content = db.Column(db.Text, nullable=False)
    variables = db.Column(db.Text)  # JSON格式的变量定义
    enabled = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'notification_type': self.notification_type,
            'template_content': self.template_content,
            'variables': json.loads(self.variables) if self.variables else [],
            'enabled': self.enabled,
            'is_default': self.is_default
        }

class EscalationPolicy(db.Model):
    """升级策略模型"""
    __tablename__ = 'escalation_policies'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    severity_levels = db.Column(db.Text)  # JSON格式的严重级别
    escalation_steps = db.Column(db.Text)  # JSON格式的升级步骤
    repeat_interval = db.Column(db.Integer, default=3600)  # 重复间隔（秒）
    max_escalations = db.Column(db.Integer, default=3)  # 最大升级次数
    notify_on_resolve = db.Column(db.Boolean, default=True)
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'severity_levels': json.loads(self.severity_levels) if self.severity_levels else [],
            'escalation_steps': json.loads(self.escalation_steps) if self.escalation_steps else [],
            'repeat_interval': self.repeat_interval,
            'max_escalations': self.max_escalations,
            'notify_on_resolve': self.notify_on_resolve,
            'enabled': self.enabled
        }

class SNMPSetting(db.Model):
    """SNMP配置模型"""
    __tablename__ = 'snmp_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    version = db.Column(db.String(10), default='v2c')  # v1, v2c, v3
    community = db.Column(db.String(100))
    security_level = db.Column(db.String(20))  # v3 only: noAuthNoPriv, authNoPriv, authPriv
    auth_protocol = db.Column(db.String(20))  # v3 only: MD5, SHA
    auth_password = db.Column(db.String(100))
    priv_protocol = db.Column(db.String(20))  # v3 only: DES, AES
    priv_password = db.Column(db.String(100))
    username = db.Column(db.String(100))  # v3 only
    context_name = db.Column(db.String(100))
    timeout = db.Column(db.Integer, default=5)
    retries = db.Column(db.Integer, default=3)
    port = db.Column(db.Integer, default=161)
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'community': self.community,
            'security_level': self.security_level,
            'auth_protocol': self.auth_protocol,
            'auth_password': '***' if self.auth_password else None,
            'priv_protocol': self.priv_protocol,
            'priv_password': '***' if self.priv_password else None,
            'username': self.username,
            'context_name': self.context_name,
            'timeout': self.timeout,
            'retries': self.retries,
            'port': self.port,
            'enabled': self.enabled
        }






class Credential(db.Model):
    """凭据管理模型"""
    __tablename__ = 'credentials'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(500), nullable=False)
    credential_type = db.Column(db.String(20), default='password')  # password, ssh_key, certificate
    protocol = db.Column(db.String(20))  # ssh, telnet, http, https
    port = db.Column(db.Integer)
    domain = db.Column(db.String(200))
    private_key = db.Column(db.Text)
    passphrase = db.Column(db.String(200))
    enabled = db.Column(db.Boolean, default=True)
    description = db.Column(db.Text)
    tags = db.Column(db.Text)  # JSON格式的标签
    last_used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def set_password(self, password):
        """设置加密密码"""
        if password:
            self.password = CredentialEncryptor.encrypt(password)
    
    def get_password(self):
        """获取解密密码（谨慎使用）"""
        return CredentialEncryptor.decrypt(self.password)
    
    def set_private_key(self, private_key):
        """设置加密私钥"""
        if private_key:
            self.private_key = CredentialEncryptor.encrypt(private_key)
    
    def get_private_key(self):
        """获取解密私钥（谨慎使用）"""
        return CredentialEncryptor.decrypt(self.private_key)
    
    def set_passphrase(self, passphrase):
        """设置加密密钥密码"""
        if passphrase:
            self.passphrase = CredentialEncryptor.encrypt(passphrase)
    
    def get_passphrase(self):
        """获取解密的密钥密码（谨慎使用）"""
        return CredentialEncryptor.decrypt(self.passphrase)
    
    def to_dict(self):
        """转换为字典（安全版本，不返回真实密码）"""
        return {
            'id': self.id,
            'name': self.name,
            'username': self.username,
            'password': '***' if self.password else None,
            'credential_type': self.credential_type,
            'protocol': self.protocol,
            'port': self.port,
            'domain': self.domain,
            'private_key': '***' if self.private_key else None,
            'passphrase': '***' if self.passphrase else None,
            'enabled': self.enabled,
            'description': self.description,
            'tags': json.loads(self.tags) if self.tags else [],
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def to_dict_with_decrypted(self):
        """转换为字典（包含解密信息，仅限管理员使用）"""
        result = self.to_dict()
        # 添加解密后的字段（使用时需要谨慎）
        result['password_decrypted'] = self.get_password()
        result['private_key_decrypted'] = self.get_private_key()
        result['passphrase_decrypted'] = self.get_passphrase()
        return result

class DiscoveryConfig(db.Model):
    """发现配置模型"""
    __tablename__ = 'discovery_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    scan_type = db.Column(db.String(20), default='ping')  # ping, port, snmp, custom
    target_range = db.Column(db.Text, nullable=False)  # IP范围或列表
    ports = db.Column(db.Text)  # JSON格式的端口列表
    snmp_community = db.Column(db.String(100))
    snmp_version = db.Column(db.String(10), default='2c')  # v1, v2c, v3
    snmp_retries = db.Column(db.Integer, default=2)
    timeout = db.Column(db.Integer, default=5)
    max_threads = db.Column(db.Integer, default=50)
    device_type = db.Column(db.String(50), default='unknown')  # 导入时默认设备类型
    cabinet_id = db.Column(db.Integer, nullable=True)  # 关联机柜ID
    manufacturer = db.Column(db.String(100))  # 厂商
    use_ping = db.Column(db.Boolean, default=True)  # 导入时是否ping检测
    auto_naming = db.Column(db.Boolean, default=True)  # 自动命名
    schedule_type = db.Column(db.String(20), default='manual')  # manual, daily, weekly, monthly
    schedule_config = db.Column(db.Text)  # JSON格式的调度配置
    auto_add_devices = db.Column(db.Boolean, default=False)
    enabled = db.Column(db.Boolean, default=True)
    last_run_at = db.Column(db.DateTime)
    last_run_status = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'scan_type': self.scan_type,
            'target_range': self.target_range,
            'ports': json.loads(self.ports) if self.ports else [],
            'snmp_community': self.snmp_community,
            'snmp_version': self.snmp_version,
            'snmp_retries': self.snmp_retries,
            'timeout': self.timeout,
            'max_threads': self.max_threads,
            'device_type': self.device_type,
            'cabinet_id': self.cabinet_id,
            'manufacturer': self.manufacturer,
            'use_ping': self.use_ping,
            'auto_naming': self.auto_naming,
            'schedule_type': self.schedule_type,
            'schedule_config': json.loads(self.schedule_config) if self.schedule_config else {},
            'auto_add_devices': self.auto_add_devices,
            'enabled': self.enabled,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'last_run_status': self.last_run_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def get_scan_type_display(self):
        """获取扫描类型显示名称"""
        scan_types = {
            'ping': 'Ping扫描',
            'port': '端口扫描',
            'snmp': 'SNMP扫描',
            'custom': '自定义扫描'
        }
        return scan_types.get(self.scan_type, self.scan_type)
    
    def get_schedule_type_display(self):
        """获取调度类型显示名称"""
        schedule_types = {
            'manual': '手动执行',
            'daily': '每日',
            'weekly': '每周',
            'monthly': '每月'
        }
        return schedule_types.get(self.schedule_type, self.schedule_type)
    
    def get_status_display(self):
        """获取状态显示名称"""
        if not self.enabled:
            return '已禁用'
        elif self.last_run_status:
            status_map = {
                'running': '运行中',
                'completed': '已完成',
                'failed': '失败',
                'stopped': '已停止'
            }
            return status_map.get(self.last_run_status, self.last_run_status)
        else:
            return '未运行'



# 正确的关联表定义
role_permissions = db.Table('role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id'), primary_key=True)
)

class Role(db.Model):
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(200))
    is_system = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 正确的多对多关系定义，指向关联表 role_permissions
    permissions = db.relationship('Permission', secondary=role_permissions, lazy='subquery',
                                  backref=db.backref('roles', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_system': self.is_system,
            'permission_ids': [p.id for p in self.permissions]  # 从关系对象获取ID列表
        }
class Permission(db.Model):
    """权限模型"""
    __tablename__ = 'permissions'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50), default='general')
    module = db.Column(db.String(50))  # 所属模块
    is_system = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'module': self.module,
            'is_system': self.is_system,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def get_category_display(self):
        """获取分类显示名称"""
        category_map = {
            'system': '系统',
            'config': '配置',
            'user': '用户',
            'permission': '权限',
            'device': '设备',
            'report': '报告',
            'general': '通用'
        }
        return category_map.get(self.category, self.category)
    
    def get_module_display(self):
        """获取模块显示名称"""
        module_map = {
            'system': '系统管理',
            'config': '配置管理',
            'user': '用户管理',
            'permission': '权限管理',
            'device': '设备管理',
            'report': '报告管理'
        }
        return module_map.get(self.module, self.module) if self.module else '未分类'
    
    def is_editable(self):
        """检查权限是否可编辑"""
        return not self.is_system


class UserRole(db.Model):
    """用户角色关联模型"""
    __tablename__ = 'user_roles'
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), primary_key=True)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 使用完整的模块路径引用
    #user = db.relationship('models.models.User', back_populates='user_roles')
    #role = db.relationship('Role')

class SystemLog(db.Model):
    """系统日志模型"""
    __tablename__ = 'system_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    level = db.Column(db.String(20), default='info')  # debug, info, warning, error, critical
    module = db.Column(db.String(100), index=True)
    source = db.Column(db.String(200))
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text)  # JSON格式的详细日志
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    ip_address = db.Column(db.String(45))
    request_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User')

    def to_dict(self):
        # 定义东八区时区
        beijing_tz = pytz.timezone('Asia/Shanghai')
        
        # 将 UTC 时间转换为北京时间
        local_timestamp = None
        if self.timestamp:
            utc_time = self.timestamp.replace(tzinfo=timezone.utc)
            local_time = utc_time.astimezone(beijing_tz)
            local_timestamp = local_time.isoformat()  # 或者格式化为字符串 'YYYY-MM-DD HH:mm:ss'

        return {
            'id': self.id,
            'timestamp': local_timestamp,  # <-- 这里已经是北京时间
            'level': self.level,
            'module': self.module,
            'source': self.source,
            'message': self.message,
            'details': json.loads(self.details) if self.details else {},
            'user_id': self.user_id,
            'user_name': self.user.username if self.user else None,
            'ip_address': self.ip_address,
            'request_id': self.request_id
        }




class LogSetting(db.Model):
    """日志设置模型"""
    __tablename__ = 'log_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    log_type = db.Column(db.String(50), unique=True, nullable=False)  # system, audit, access, error
    enabled = db.Column(db.Boolean, default=True)
    level = db.Column(db.String(20), default='info')  # debug, info, warning, error, critical
    retention_days = db.Column(db.Integer, default=30)
    max_file_size = db.Column(db.Integer, default=10)  # MB
    max_files = db.Column(db.Integer, default=10)
    output_format = db.Column(db.String(20), default='json')  # json, text
    destinations = db.Column(db.Text)  # JSON格式的输出目标
    filters = db.Column(db.Text)  # JSON格式的过滤器
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'log_type': self.log_type,
            'enabled': self.enabled,
            'level': self.level,
            'retention_days': self.retention_days,
            'max_file_size': self.max_file_size,
            'max_files': self.max_files,
            'output_format': self.output_format,
            'destinations': json.loads(self.destinations) if self.destinations else [],
            'filters': json.loads(self.filters) if self.filters else {}
        }


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    action = db.Column(db.String(50), index=True)  # create, update, delete, read, login, logout
    resource_type = db.Column(db.String(100), index=True)
    resource_id = db.Column(db.String(100), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text)  # JSON格式的详细数据
    changes = db.Column(db.Text)  # JSON格式的变更记录
    status = db.Column(db.String(20), default='success')  # success, failure, partial
    request_method = db.Column(db.String(10))
    request_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User')

    @property
    def local_timestamp(self):
        """返回 UTC+8 北京时间"""
        if self.timestamp:
            return self.timestamp + timedelta(hours=8)
        return None

    @property
    def local_created_at(self):
        """返回 UTC+8 北京时间"""
        if self.created_at:
            return self.created_at + timedelta(hours=8)
        return None

    def to_dict(self):
        beijing_tz = timezone(timedelta(hours=8))
        local_ts = self.local_timestamp
        return {
            'id': self.id,
            'timestamp': local_ts.isoformat() if local_ts else None,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'user_id': self.user_id,
            'user_name': self.user.username if self.user else None,
            'user_email': self.user.email if self.user else None,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'message': self.message,
            'details': json.loads(self.details) if self.details else {},
            'changes': json.loads(self.changes) if self.changes else {},
            'status': self.status,
            'request_method': self.request_method,
            'request_path': self.request_path,
            'created_at': self.local_created_at.isoformat() if self.local_created_at else None
        }

class APISetting(db.Model):
    """API设置模型"""
    __tablename__ = 'api_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    api_key = db.Column(db.String(100), unique=True, nullable=False)
    secret_key = db.Column(db.String(500))
    enabled = db.Column(db.Boolean, default=True)
    rate_limit = db.Column(db.Integer, default=100)  # 每分钟请求限制
    rate_limit_period = db.Column(db.Integer, default=60)  # 限流周期（秒）
    allowed_ips = db.Column(db.Text)  # JSON格式的允许IP列表
    allowed_methods = db.Column(db.Text)  # JSON格式的允许HTTP方法
    allowed_endpoints = db.Column(db.Text)  # JSON格式的允许端点
    permissions = db.Column(db.Text)  # JSON格式的API权限
    expires_at = db.Column(db.DateTime)
    last_used_at = db.Column(db.DateTime)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'api_key': self.api_key,
            'secret_key': '***' if self.secret_key else None,
            'enabled': self.enabled,
            'rate_limit': self.rate_limit,
            'rate_limit_period': self.rate_limit_period,
            'allowed_ips': json.loads(self.allowed_ips) if self.allowed_ips else [],
            'allowed_methods': json.loads(self.allowed_methods) if self.allowed_methods else [],
            'allowed_endpoints': json.loads(self.allowed_endpoints) if self.allowed_endpoints else [],
            'permissions': json.loads(self.permissions) if self.permissions else {},
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'description': self.description
        }

class IntegrationSetting(db.Model):
    """集成配置模型"""
    __tablename__ = 'integration_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    integration_type = db.Column(db.String(50), nullable=False)  # ticketing, monitoring, cmdb, chatops
    provider = db.Column(db.String(100), nullable=False)  # jira, servicenow, zabbix, prometheus, slack
    config = db.Column(db.Text, nullable=False)  # JSON格式的集成配置
    enabled = db.Column(db.Boolean, default=True)
    sync_enabled = db.Column(db.Boolean, default=False)
    sync_direction = db.Column(db.String(20), default='bidirectional')  # inbound, outbound, bidirectional
    sync_interval = db.Column(db.Integer, default=300)  # 同步间隔（秒）
    last_sync_at = db.Column(db.DateTime)
    last_sync_status = db.Column(db.String(20))
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'integration_type': self.integration_type,
            'provider': self.provider,
            'config': json.loads(self.config) if self.config else {},
            'enabled': self.enabled,
            'sync_enabled': self.sync_enabled,
            'sync_direction': self.sync_direction,
            'sync_interval': self.sync_interval,
            'last_sync_at': self.last_sync_at.isoformat() if self.last_sync_at else None,
            'last_sync_status': self.last_sync_status,
            'description': self.description
        }

class WebhookSetting(db.Model):
    """Webhook配置模型"""
    __tablename__ = 'webhook_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    method = db.Column(db.String(10), default='POST')  # GET, POST, PUT, DELETE
    content_type = db.Column(db.String(50), default='application/json')
    headers = db.Column(db.Text)  # JSON格式的请求头
    payload_template = db.Column(db.Text)  # JSON格式的负载模板
    secret = db.Column(db.String(500))  # 用于签名的密钥
    enabled = db.Column(db.Boolean, default=True)
    verify_ssl = db.Column(db.Boolean, default=True)
    timeout = db.Column(db.Integer, default=10)
    retry_enabled = db.Column(db.Boolean, default=False)
    max_retries = db.Column(db.Integer, default=3)
    retry_interval = db.Column(db.Integer, default=5)
    trigger_events = db.Column(db.Text)  # JSON格式的触发事件
    description = db.Column(db.Text)
    last_triggered_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'method': self.method,
            'content_type': self.content_type,
            'headers': json.loads(self.headers) if self.headers else {},
            'payload_template': self.payload_template,
            'secret': '***' if self.secret else None,
            'enabled': self.enabled,
            'verify_ssl': self.verify_ssl,
            'timeout': self.timeout,
            'retry_enabled': self.retry_enabled,
            'max_retries': self.max_retries,
            'retry_interval': self.retry_interval,
            'trigger_events': json.loads(self.trigger_events) if self.trigger_events else [],
            'description': self.description,
            'last_triggered_at': self.last_triggered_at.isoformat() if self.last_triggered_at else None
        }




