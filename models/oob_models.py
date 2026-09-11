# models/oob_models.py
"""Out-of-band (OOB) management models: iDRAC / iLO / iBMC / XCC controllers,
sensor readings and power-action audit logs."""
import json

from extensions import db
from models._base import utcnow


class BmcController(db.Model):
    """BMC controller (one per physical server)."""
    __tablename__ = 'bmc_controllers'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, unique=True, index=True)
    name = db.Column(db.String(128))
    bmc_ip = db.Column(db.String(45), index=True)
    bmc_port = db.Column(db.Integer, default=443)
    use_ssl = db.Column(db.Boolean, default=True)
    verify_ssl = db.Column(db.Boolean, default=False)
    bmc_mac = db.Column(db.String(17))
    vendor = db.Column(db.String(32))                    # dell / hpe / huawei / lenovo / inspur / ...
    protocol = db.Column(db.String(16), default='redfish')  # redfish / ipmi
    redfish_version = db.Column(db.String(32))
    firmware_version = db.Column(db.String(64))
    bios_version = db.Column(db.String(64))
    model = db.Column(db.String(64))
    serial_number = db.Column(db.String(64))
    power_state = db.Column(db.String(16))               # On / Off / PoweringOn / PoweringOff
    credential_id = db.Column(db.Integer, db.ForeignKey('credentials.id'))
    enabled = db.Column(db.Boolean, default=True, index=True)
    approval_status = db.Column(db.String(16), default='approved', index=True)  # pending / approved / rejected
    approved_at = db.Column(db.DateTime)
    approved_by = db.Column(db.String(64))
    last_poll = db.Column(db.DateTime)
    last_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    device = db.relationship('Device', backref='bmc_controller', lazy='select')
    credential = db.relationship('Credential', lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'name': self.name,
            'bmc_ip': self.bmc_ip,
            'bmc_port': self.bmc_port,
            'use_ssl': self.use_ssl if self.use_ssl is not None else True,
            'verify_ssl': self.verify_ssl if self.verify_ssl is not None else False,
            'bmc_mac': self.bmc_mac,
            'vendor': self.vendor,
            'protocol': self.protocol,
            'redfish_version': self.redfish_version,
            'credential_id': self.credential_id,
            'firmware_version': self.firmware_version,
            'bios_version': self.bios_version,
            'model': self.model,
            'serial_number': self.serial_number,
            'power_state': self.power_state,
            'enabled': self.enabled,
            'approval_status': self.approval_status or 'approved',
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'approved_by': self.approved_by,
            'last_poll': self.last_poll.isoformat() if self.last_poll else None,
            'last_error': self.last_error,
        }


class BmcSensor(db.Model):
    """BMC sensor reading snapshot (temperature / fan / voltage / power)."""
    __tablename__ = 'bmc_sensors'
    __table_args__ = (
        db.Index('idx_bmc_sensor_ctrl_time', 'controller_id', 'ts'),
    )

    id = db.Column(db.Integer, primary_key=True)
    controller_id = db.Column(db.Integer, db.ForeignKey('bmc_controllers.id'), nullable=False, index=True)
    name = db.Column(db.String(128))
    kind = db.Column(db.String(32))                      # temperature / fan / voltage / power
    reading = db.Column(db.Float)
    unit = db.Column(db.String(16))
    status = db.Column(db.String(32))                    # ok / warning / critical / unknown
    lower_warning = db.Column(db.Float)
    upper_warning = db.Column(db.Float)
    lower_critical = db.Column(db.Float)
    upper_critical = db.Column(db.Float)
    threshold_rule_id = db.Column(db.Integer, nullable=True)
    threshold_source = db.Column(db.String(16), nullable=True)   # vendor / override / none
    threshold_breach = db.Column(db.String(24), nullable=True)   # ok / warning_low / warning_high / critical_low / critical_high / unknown
    ts = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    controller = db.relationship('BmcController', backref='sensors', lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'controller_id': self.controller_id,
            'name': self.name,
            'kind': self.kind,
            'reading': self.reading,
            'unit': self.unit,
            'status': self.status,
            'lower_warning': self.lower_warning,
            'upper_warning': self.upper_warning,
            'lower_critical': self.lower_critical,
            'upper_critical': self.upper_critical,
            'threshold_rule_id': self.threshold_rule_id,
            'threshold_source': self.threshold_source,
            'threshold_breach': self.threshold_breach,
            'ts': self.ts.isoformat() if self.ts else None,
        }



class BmcSensorAlertState(db.Model):
    """Durable debounce state for one BMC sensor.

    The poller keeps this row in sync with consecutive abnormal readings so a
    single transient warning/critical sample does not create an alert. Once the
    configured strike count is reached, an AlertEvent is raised and its id is
    stored here for fast recovery/reopen handling.
    """
    __tablename__ = 'bmc_sensor_alert_states'
    __table_args__ = (
        db.UniqueConstraint('controller_id', 'sensor_name', 'sensor_kind',
                            name='uq_bmc_sensor_alert_state_ctrl_name_kind'),
        db.Index('idx_bmc_sensor_alert_state_ctrl', 'controller_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    controller_id = db.Column(db.Integer, db.ForeignKey('bmc_controllers.id'),
                              nullable=False, index=True)
    sensor_name = db.Column(db.String(128), nullable=False, default='')
    sensor_kind = db.Column(db.String(32), nullable=False, default='sensor')
    normalized_status = db.Column(db.String(16), default='ok')  # ok / warning / critical / unknown
    consecutive_strikes = db.Column(db.Integer, default=0)
    alert_id = db.Column(db.Integer, nullable=True)
    last_abnormal_at = db.Column(db.DateTime, nullable=True)
    last_ok_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    controller = db.relationship('BmcController', backref='sensor_alert_states',
                                 lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'controller_id': self.controller_id,
            'sensor_name': self.sensor_name,
            'sensor_kind': self.sensor_kind,
            'normalized_status': self.normalized_status,
            'consecutive_strikes': self.consecutive_strikes,
            'alert_id': self.alert_id,
            'last_abnormal_at': self.last_abnormal_at.isoformat() if self.last_abnormal_at else None,
            'last_ok_at': self.last_ok_at.isoformat() if self.last_ok_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }




class BmcSensorThreshold(db.Model):
    """Optional per-controller/per-sensor threshold overrides for BMC sensors.

    Rows are resolved from most specific to least specific during polling:
    controller_id + name + kind, controller_id + kind, controller_id + name,
    controller_id only, then global rows where controller_id is null.
    Vendor-provided thresholds remain the fallback when no override matches.
    """
    __tablename__ = 'bmc_sensor_thresholds'
    __table_args__ = (
        db.Index('idx_bmc_sensor_threshold_lookup',
                 'controller_id', 'kind', 'name', 'enabled'),
    )

    id = db.Column(db.Integer, primary_key=True)
    controller_id = db.Column(db.Integer, db.ForeignKey('bmc_controllers.id'),
                              nullable=True, index=True)
    name = db.Column(db.String(128), nullable=True)      # exact sensor name, nullable = any
    kind = db.Column(db.String(32), nullable=True)       # temperature / fan / voltage / power
    lower_warning = db.Column(db.Float, nullable=True)
    upper_warning = db.Column(db.Float, nullable=True)
    lower_critical = db.Column(db.Float, nullable=True)
    upper_critical = db.Column(db.Float, nullable=True)
    enabled = db.Column(db.Boolean, default=True, index=True)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    controller = db.relationship('BmcController', backref='sensor_thresholds',
                                 lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'controller_id': self.controller_id,
            'name': self.name,
            'kind': self.kind,
            'lower_warning': self.lower_warning,
            'upper_warning': self.upper_warning,
            'lower_critical': self.lower_critical,
            'upper_critical': self.upper_critical,
            'enabled': self.enabled,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }



class BmcPowerLog(db.Model):
    """Audit log for power actions performed against a BMC."""
    __tablename__ = 'bmc_power_logs'

    id = db.Column(db.Integer, primary_key=True)
    controller_id = db.Column(db.Integer, db.ForeignKey('bmc_controllers.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(32), nullable=False)    # power_on / power_off / reset / ...
    result = db.Column(db.String(16), default='success')
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)

    controller = db.relationship('BmcController', backref='power_logs', lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'controller_id': self.controller_id,
            'user_id': self.user_id,
            'action': self.action,
            'result': self.result,
            'message': self.message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class BmcEventLog(db.Model):
    """Persisted BMC event log (SEL / Lifecycle) entries for alert linkage."""
    __tablename__ = 'bmc_event_logs'
    __table_args__ = (
        db.Index('idx_bmc_event_ctrl_time', 'controller_id', 'log_time'),
    )

    id = db.Column(db.Integer, primary_key=True)
    controller_id = db.Column(db.Integer, db.ForeignKey('bmc_controllers.id'),
                              nullable=False, index=True)
    entry_type = db.Column(db.String(32))      # SEL / Lifecycle / ...
    severity = db.Column(db.String(32))        # Ok / Warning / Critical
    message = db.Column(db.Text)
    message_id = db.Column(db.String(128), index=True)
    sensor_type = db.Column(db.String(64))
    event_id = db.Column(db.String(64))
    log_time = db.Column(db.DateTime, index=True)      # Created timestamp on BMC
    recorded_at = db.Column(db.DateTime, default=utcnow)
    alerted = db.Column(db.Boolean, default=False)     # whether an alert was raised

    controller = db.relationship('BmcController', backref='event_logs', lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'controller_id': self.controller_id,
            'entry_type': self.entry_type,
            'severity': self.severity,
            'message': self.message,
            'message_id': self.message_id,
            'sensor_type': self.sensor_type,
            'event_id': self.event_id,
            'log_time': self.log_time.isoformat() if self.log_time else None,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
            'alerted': self.alerted,
        }


class BmcConfigBackup(db.Model):
    """BMC 配置快照（对标 DCOS「服务器备份」）：BIOS 属性 / 网络 / 系统信息。"""
    __tablename__ = 'bmc_config_backups'

    id = db.Column(db.Integer, primary_key=True)
    controller_id = db.Column(db.Integer, db.ForeignKey('bmc_controllers.id'),
                              nullable=False, index=True)
    name = db.Column(db.String(128))
    config_json = db.Column(db.Text)                     # 完整快照（JSON）
    checksum = db.Column(db.String(64))                 # 快照内容 sha256
    operator = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=utcnow)

    controller = db.relationship('BmcController', backref='config_backups', lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'controller_id': self.controller_id,
            'name': self.name,
            'checksum': self.checksum,
            'operator': self.operator,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'size': len(self.config_json) if self.config_json else 0,
        }

    def get_config(self):
        if not self.config_json:
            return {}
        try:
            return json.loads(self.config_json)
        except (ValueError, TypeError):
            return {}


class BiosTemplate(db.Model):
    """Named BIOS attribute template, distributable to multiple controllers."""
    __tablename__ = 'bios_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    vendor = db.Column(db.String(64), nullable=True)        # dell/hpe/huawei/...
    description = db.Column(db.Text, nullable=True)
    attributes_json = db.Column(db.Text, nullable=False)    # JSON: {key: value}
    source_controller_id = db.Column(db.Integer,
                                     db.ForeignKey('bmc_controllers.id'),
                                     nullable=True)
    creator = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'vendor': self.vendor,
            'description': self.description,
            'attribute_count': len(self.get_attributes()),
            'source_controller_id': self.source_controller_id,
            'creator': self.creator,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def get_attributes(self):
        if not self.attributes_json:
            return {}
        try:
            return json.loads(self.attributes_json)
        except (ValueError, TypeError):
            return {}


class BmcAssetDrift(db.Model):
    """BMC-discovered values that do not match the CMDB asset record."""
    __tablename__ = 'bmc_asset_drifts'
    __table_args__ = (
        db.Index('idx_bmc_asset_drift_ctrl_field', 'controller_id', 'field_name', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    controller_id = db.Column(db.Integer, db.ForeignKey('bmc_controllers.id'), nullable=False, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True, index=True)
    field_name = db.Column(db.String(64), nullable=False)
    expected_value = db.Column(db.Text, nullable=True)
    discovered_value = db.Column(db.Text, nullable=True)
    severity = db.Column(db.String(16), default='warning')  # info / warning / critical
    status = db.Column(db.String(16), default='open', index=True)  # open / acknowledged / ignored / resolved
    source = db.Column(db.String(32), default='redfish_poll')
    check_time = db.Column(db.DateTime, default=utcnow, index=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.String(64), nullable=True)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    controller = db.relationship('BmcController', backref='asset_drifts', lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'controller_id': self.controller_id,
            'device_id': self.device_id,
            'field_name': self.field_name,
            'expected_value': self.expected_value,
            'discovered_value': self.discovered_value,
            'severity': self.severity,
            'status': self.status,
            'source': self.source,
            'check_time': self.check_time.isoformat() if self.check_time else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolved_by': self.resolved_by,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class BmcFirmwareJob(db.Model):
    """Audit record for a firmware upgrade task triggered via OOB."""
    __tablename__ = 'bmc_firmware_jobs'

    id = db.Column(db.Integer, primary_key=True)
    controller_id = db.Column(db.Integer, db.ForeignKey('bmc_controllers.id'),
                              nullable=False)
    image_url = db.Column(db.String(512), nullable=False)
    transfer_protocol = db.Column(db.String(16), default='HTTP')
    status = db.Column(db.String(16), default='submitted')
    # submitted / running / success / failed
    task_ref = db.Column(db.String(256), nullable=True)      # Redfish Task URI
    error = db.Column(db.Text, nullable=True)
    operator = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)

    controller = db.relationship('BmcController', backref='firmware_jobs', lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'controller_id': self.controller_id,
            'image_url': self.image_url,
            'transfer_protocol': self.transfer_protocol,
            'status': self.status,
            'task_ref': self.task_ref,
            'error': self.error,
            'operator': self.operator,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
        }

