"""合规管理、配置基线、配置版本控制模型"""
from datetime import datetime
from extensions import db


class ConfigBaseline(db.Model):
    """配置基线"""
    __tablename__ = 'config_baselines'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False, index=True)
    config_type = db.Column(db.String(30), nullable=False, comment='类型: running/startup/vlan/interface')
    content = db.Column(db.Text, nullable=False, comment='配置内容')
    hash = db.Column(db.String(64), comment='内容哈希(SHA256)')
    captured_at = db.Column(db.DateTime, default=datetime.utcnow, comment='捕获时间')
    captured_by = db.Column(db.String(20), default='manual', comment='捕获方式: manual/scheduled')
    is_active = db.Column(db.Boolean, default=True, comment='是否为当前基线')
    description = db.Column(db.String(200), comment='描述')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    device = db.relationship('Device', backref='config_baselines')

    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'config_type': self.config_type,
            'hash': self.hash,
            'captured_at': self.captured_at.isoformat() if self.captured_at else None,
            'captured_by': self.captured_by,
            'is_active': self.is_active,
        }


class ConfigDrift(db.Model):
    """配置漂移记录"""
    __tablename__ = 'config_drifts'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False, index=True)
    baseline_id = db.Column(db.Integer, db.ForeignKey('config_baselines.id', ondelete='SET NULL'))
    drift_type = db.Column(db.String(20), comment='类型: added/removed/modified')
    before_content = db.Column(db.Text, comment='变更前内容')
    after_content = db.Column(db.Text, comment='变更后内容')
    diff_summary = db.Column(db.String(500), comment='变更摘要')
    detected_at = db.Column(db.DateTime, default=datetime.utcnow, comment='检测时间')
    severity = db.Column(db.String(20), default='medium', comment='严重度: low/medium/high/critical')
    status = db.Column(db.String(20), default='open', comment='状态: open/acknowledged/resolved/ignored')
    resolved_at = db.Column(db.DateTime, comment='解决时间')
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes = db.Column(db.Text, comment='备注')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    device = db.relationship('Device', backref='config_drifts')
    baseline = db.relationship('ConfigBaseline', backref='drifts')

    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'drift_type': self.drift_type,
            'diff_summary': self.diff_summary,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'severity': self.severity,
            'status': self.status,
        }


class ConfigVersion(db.Model):
    """配置版本历史"""
    __tablename__ = 'config_versions'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False, index=True)
    version_number = db.Column(db.Integer, nullable=False, comment='版本号')
    config_type = db.Column(db.String(30), nullable=False, comment='类型: running/startup')
    content = db.Column(db.Text, nullable=False, comment='配置内容')
    change_summary = db.Column(db.String(500), comment='变更摘要')
    checksum = db.Column(db.String(64), comment='内容校验和')
    changed_by = db.Column(db.String(100), comment='变更人')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    device = db.relationship('Device', backref='config_versions')

    __table_args__ = (
        db.UniqueConstraint('device_id', 'config_type', 'version_number', name='uq_device_config_version'),
    )


class CompliancePolicy(db.Model):
    """合规策略"""
    __tablename__ = 'compliance_policies'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, comment='策略名称')
    description = db.Column(db.Text, comment='描述')
    category = db.Column(db.String(30), nullable=False, comment='分类: security/network/system')
    check_type = db.Column(db.String(30), nullable=False, comment='检查类型: config/performance/accessibility')
    check_expression = db.Column(db.Text, comment='检查规则(JSON)')
    severity = db.Column(db.String(20), default='medium', comment='严重度: critical/high/medium/low')
    framework = db.Column(db.String(50), comment='所属框架: ISO27001/SOX/PCI/等')
    control_id = db.Column(db.String(50), comment='控制项编号')
    enabled = db.Column(db.Boolean, default=True)
    auto_remediate = db.Column(db.Boolean, default=False, comment='是否自动修复')
    remediation_script = db.Column(db.Text, comment='修复脚本')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'check_type': self.check_type,
            'severity': self.severity,
            'framework': self.framework,
            'control_id': self.control_id,
            'enabled': self.enabled,
        }


class ComplianceCheckResult(db.Model):
    """合规检查结果"""
    __tablename__ = 'compliance_check_results'

    id = db.Column(db.Integer, primary_key=True)
    policy_id = db.Column(db.Integer, db.ForeignKey('compliance_policies.id', ondelete='CASCADE'), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False)
    status = db.Column(db.String(20), nullable=False, comment='结果: pass/fail/error/na')
    actual_value = db.Column(db.Text, comment='实际值')
    expected_value = db.Column(db.Text, comment='期望值')
    detail = db.Column(db.Text, comment='详情')
    checked_at = db.Column(db.DateTime, default=datetime.utcnow, comment='检查时间')
    checked_by = db.Column(db.String(50), comment='检查方式: auto/manual')

    policy = db.relationship('CompliancePolicy', backref='check_results')
    device = db.relationship('Device', backref='compliance_checks')


class BackupVerification(db.Model):
    """备份验证记录"""
    __tablename__ = 'backup_verifications'

    id = db.Column(db.Integer, primary_key=True)
    backup_config_id = db.Column(db.Integer, db.ForeignKey('backup_configs.id', ondelete='CASCADE'), nullable=False)
    verified_at = db.Column(db.DateTime, default=datetime.utcnow, comment='验证时间')
    status = db.Column(db.String(20), nullable=False, comment='结果: verified/failed/partial')
    file_size = db.Column(db.BigInteger, comment='文件大小(字节)')
    checksum = db.Column(db.String(64), comment='校验和')
    restore_test_result = db.Column(db.String(20), comment='恢复测试: pass/fail/not_tested')
    duration_seconds = db.Column(db.Integer, comment='验证耗时(秒)')
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), comment='验证人')
    notes = db.Column(db.Text, comment='备注')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    backup_config = db.relationship('BackupConfig', backref='verifications')
