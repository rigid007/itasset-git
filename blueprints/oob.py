# blueprints/oob.py
"""OOB (out-of-band) management blueprint: controllers, sensors, power actions."""
import hashlib
import io
import json
import logging
from collections import Counter
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, Response, make_response, current_app
from flask_login import login_required, current_user
from sqlalchemy import text, or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.oob_models import (BmcController, BmcSensor, BmcSensorAlertState,
                               BmcSensorThreshold, BmcPowerLog, BmcEventLog,
                               BmcConfigBackup, BiosTemplate,
                               BmcFirmwareJob, BmcAssetDrift)
from services.oob_manager import OobManager, OobError, RESET_TYPES

logger = logging.getLogger(__name__)

oob_bp = Blueprint('oob', __name__, url_prefix='/oob')

# 厂商下拉候选（含通用占位）
VENDOR_CHOICES = ['dell', 'hpe', 'huawei', 'lenovo', 'inspur', 'other']
PROTOCOL_CHOICES = ['redfish', 'ipmi']


def _parse_bool(value, default=False):
    """Parse JSON/string booleans so API clients and HTML forms behave alike."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'y', 'on'):
        return True
    if text in ('0', 'false', 'no', 'n', 'off', ''):
        return False
    return default


def _parse_port(value, default=443):
    """Validate and normalize a BMC TCP port."""
    if value in (None, '', 0):
        return default
    port = int(value)
    if not (1 <= port <= 65535):
        raise ValueError('port must be between 1 and 65535')
    return port


def _empty_to_none(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_optional_float(value):
    if value in (None, ''):
        return None
    return float(value)


def _create_sensor_threshold(controller_id):
    d = request.get_json(force=True) or {}
    try:
        row = BmcSensorThreshold(
            controller_id=controller_id,
            name=_empty_to_none(d.get('name')),
            kind=_empty_to_none(d.get('kind')),
            lower_warning=_parse_optional_float(d.get('lower_warning')),
            upper_warning=_parse_optional_float(d.get('upper_warning')),
            lower_critical=_parse_optional_float(d.get('lower_critical')),
            upper_critical=_parse_optional_float(d.get('upper_critical')),
            enabled=_parse_bool(d.get('enabled'), True),
            description=_empty_to_none(d.get('description')),
        )
    except (TypeError, ValueError) as e:
        return jsonify({'error': str(e)}), 400
    db.session.add(row)
    db.session.commit()
    return jsonify(row.to_dict()), 201


def _enrich(ctrl):
    """补充 device_name / credential_name 便于前端展示。"""
    d = ctrl.to_dict()
    d['device_name'] = ctrl.device.name if ctrl.device else None
    d['credential_name'] = ctrl.credential.name if ctrl.credential else None
    return d


@oob_bp.route('/')
@login_required
def index():
    controllers = BmcController.query.order_by(BmcController.name).all()
    return render_template('oob/index.html', controllers=controllers)


@oob_bp.route('/api/controllers')
@login_required
def list_controllers():
    controllers = BmcController.query.order_by(BmcController.name).all()
    return jsonify([_enrich(c) for c in controllers])


@oob_bp.route('/api/devices')
@login_required
def selectable_devices():
    """返回可用于绑定 BMC 的设备列表（id + 名称 + 管理 IP + 类型）。"""
    from models.models import Device
    devices = (Device.query
               .filter(Device.device_type.isnot(None))
               .order_by(Device.name).all())
    out = [{
        'id': d.id,
        'name': d.name,
        'management_ip': d.management_ip,
        'device_type': d.device_type,
        'model': d.model,
    } for d in devices]
    return jsonify(out)


@oob_bp.route('/api/discovery/candidates')
@login_required
def discovery_candidates():
    """Suggest BMC controllers for devices that do not have one yet.

    The scan is intentionally conservative:
      * only enabled credentials are tried;
      * only Redfish is probed (no destructive action is performed);
      * each device IP stops at the first successful credential.
    """
    from models.config_models import Credential
    from models.models import Device

    credential_id = request.args.get('credential_id', type=int)
    limit = min(request.args.get('limit', 100, type=int), 500)
    ip_prefix = (request.args.get('ip_prefix') or '').strip()
    device_type = (request.args.get('device_type') or '').strip()
    if credential_id:
        creds = [Credential.query.get(credential_id)]
    else:
        creds = (Credential.query.filter_by(enabled=True)
                 .order_by(Credential.id).all())
    creds = [c for c in creds if c is not None and c.enabled]
    if not creds:
        return jsonify({'candidates': []})

    existing_device_ids = [cid for (cid,) in db.session.query(
        BmcController.device_id).filter(BmcController.device_id.isnot(None),
                                        BmcController.approval_status != 'rejected').all()]
    q = (Device.query
         .filter(Device.management_ip.isnot(None), Device.management_ip != '')
         .order_by(Device.name))
    if ip_prefix:
        q = q.filter(Device.management_ip.like(ip_prefix + '%'))
    if device_type:
        q = q.filter(Device.device_type == device_type)
    if existing_device_ids:
        q = q.filter(~Device.id.in_(existing_device_ids))
    devices = q.limit(limit).all()

    candidates = []
    for dev in devices:
        ip = (dev.management_ip or '').strip()
        if not ip:
            continue
        for cred in creds:
            probe_ctrl = type('ProbeBmcController', (), {
                'bmc_ip': ip,
                'protocol': 'redfish',
            })()
            mgr = OobManager(probe_ctrl, cred, timeout=2, retries=0)
            try:
                info = mgr.probe()
            except OobError:
                continue
            except Exception as exc:
                logger.debug('BMC probe failed %s/%s: %s', ip, cred.name, exc)
                continue
            if not info or not info.get('reachable'):
                continue
            candidates.append({
                'device_id': dev.id,
                'device_name': dev.name,
                'management_ip': ip,
                'bmc_ip': ip,
                'credential_id': cred.id,
                'credential_name': cred.name,
                'vendor': info.get('vendor') or 'unknown',
                'manufacturer': info.get('manufacturer') or '',
                'model': info.get('model') or '',
                'serial_number': info.get('serial_number') or '',
                'redfish_version': info.get('redfish_version') or '',
                'firmware_version': info.get('firmware_version') or '',
                'bios_version': info.get('bios_version') or '',
                'power_state': info.get('power_state') or '',
            })
            break
    return jsonify({'candidates': candidates})


@oob_bp.route('/api/controllers/<int:cid>/test-connection', methods=['POST'])
@login_required
def test_saved_controller_connection(cid):
    """Test an already-saved controller with its stored credential/TLS settings."""
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'ok': False, 'error': 'no credential configured'}), 400
    mgr = OobManager(ctrl, ctrl.credential, timeout=5, retries=0)
    try:
        info = mgr.test_connection()
    except OobError as e:
        return jsonify({'ok': False, 'error': str(e)}), 502
    info['ok'] = True
    info['controller_id'] = ctrl.id
    info['credential_name'] = ctrl.credential.name
    info['bmc_ip'] = ctrl.bmc_ip
    info['bmc_port'] = ctrl.bmc_port or 443
    info['use_ssl'] = ctrl.use_ssl if ctrl.use_ssl is not None else True
    info['verify_ssl'] = bool(ctrl.verify_ssl)
    return jsonify(info)


@oob_bp.route('/api/controllers/<int:cid>/probe')
@login_required
def probe_controller(cid):
    """Run a lightweight Redfish probe without persisting sensors/logs."""
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'error': 'no credential configured'}), 400
    mgr = OobManager(ctrl, ctrl.credential)
    try:
        info = mgr.probe()
    except OobError as e:
        return jsonify({'error': str(e)}), 502
    # Best-effort enrichment of existing controller inventory fields.
    for src_field, dst_field in (
        ('vendor', 'vendor'),
        ('model', 'model'),
        ('serial_number', 'serial_number'),
        ('firmware_version', 'firmware_version'),
        ('bios_version', 'bios_version'),
        ('redfish_version', 'redfish_version'),
    ):
        value = info.get(src_field)
        if value:
            setattr(ctrl, dst_field, value)
    db.session.commit()
    return jsonify(info)


@oob_bp.route('/api/controllers/test-connection', methods=['POST'])
@login_required
def test_connection():
    """Test Redfish connectivity/auth with explicit BMC connection settings."""
    from models.config_models import Credential
    d = request.get_json(force=True) or {}
    bmc_ip = (d.get('bmc_ip') or '').strip()
    credential_id = d.get('credential_id')
    if not bmc_ip:
        return jsonify({'ok': False, 'error': 'bmc_ip is required'}), 400
    if not credential_id:
        return jsonify({'ok': False, 'error': 'credential_id is required'}), 400
    cred = Credential.query.get(credential_id)
    if cred is None or not cred.enabled:
        return jsonify({'ok': False, 'error': 'credential not found or disabled'}), 400
    try:
        bmc_port = _parse_port(d.get('bmc_port'), 443)
    except (TypeError, ValueError) as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    probe_ctrl = type('TestBmcController', (), {
        'bmc_ip': bmc_ip,
        'bmc_port': bmc_port,
        'use_ssl': _parse_bool(d.get('use_ssl'), True),
        'verify_ssl': _parse_bool(d.get('verify_ssl'), False),
        'protocol': (d.get('protocol') or 'redfish').strip() or 'redfish',
    })()
    mgr = OobManager(probe_ctrl, cred, timeout=5, retries=0)
    try:
        info = mgr.test_connection()
    except OobError as e:
        return jsonify({'ok': False, 'error': str(e)}), 502
    info['ok'] = True
    info['credential_name'] = cred.name
    info['bmc_ip'] = bmc_ip
    info['bmc_port'] = bmc_port
    info['use_ssl'] = probe_ctrl.use_ssl
    info['verify_ssl'] = probe_ctrl.verify_ssl
    return jsonify(info)


@oob_bp.route('/api/controllers', methods=['POST'])
@login_required
def create_controller():
    d = request.get_json(force=True)
    if not d.get('bmc_ip'):
        return jsonify({'error': 'bmc_ip 必填'}), 400
    device_id = d.get('device_id')
    approval_status = d.get('approval_status') or 'approved'
    if approval_status not in ('pending', 'approved', 'rejected'):
        approval_status = 'approved'
    enabled = bool(d.get('enabled', approval_status != 'pending'))
    if approval_status == 'pending':
        enabled = False

    ctrl = None
    if device_id is not None:
        dup = BmcController.query.filter_by(device_id=device_id).first()
        if dup:
            if dup.approval_status == 'rejected':
                # Allow re-submitting a previously rejected candidate.
                ctrl = dup
            else:
                return jsonify({'error': 'device already bound to BMC controller (id=%s)' % dup.id}), 409
    if ctrl is None:
        ctrl = BmcController(device_id=device_id)
    ctrl.name = (d.get('name') or '').strip() or None
    ctrl.bmc_ip = (d.get('bmc_ip') or '').strip()
    try:
        ctrl.bmc_port = _parse_port(d.get('bmc_port'), 443)
    except (TypeError, ValueError) as e:
        return jsonify({'error': str(e)}), 400
    ctrl.use_ssl = _parse_bool(d.get('use_ssl'), True)
    ctrl.verify_ssl = _parse_bool(d.get('verify_ssl'), False)
    ctrl.bmc_mac = d.get('bmc_mac')
    ctrl.vendor = d.get('vendor')
    ctrl.protocol = (d.get('protocol') or 'redfish').strip() or 'redfish'
    ctrl.credential_id = d.get('credential_id')
    ctrl.enabled = enabled
    ctrl.approval_status = approval_status
    if approval_status == 'approved':
        ctrl.approved_at = datetime.now()
        ctrl.approved_by = getattr(current_user, 'username', str(current_user.id))
    else:
        ctrl.approved_at = None
        ctrl.approved_by = None

    db.session.add(ctrl)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'save failed: duplicate device id or invalid field'}), 409
    return jsonify(ctrl.to_dict()), 201


@oob_bp.route('/api/controllers/<int:cid>', methods=['GET'])
@login_required
def get_controller(cid):
    ctrl = BmcController.query.get_or_404(cid)
    return jsonify(ctrl.to_dict())


@oob_bp.route('/api/controllers/<int:cid>/approve', methods=['POST'])
@login_required
def approve_controller(cid):
    """Approve a pending BMC candidate and enable polling."""
    ctrl = BmcController.query.get_or_404(cid)
    ctrl.approval_status = 'approved'
    ctrl.enabled = True
    ctrl.approved_at = datetime.now()
    ctrl.approved_by = getattr(current_user, 'username', str(current_user.id))
    db.session.commit()
    return jsonify(ctrl.to_dict())


@oob_bp.route('/api/controllers/<int:cid>/reject', methods=['POST'])
@login_required
def reject_controller(cid):
    """Reject a pending BMC candidate without deleting the audit row."""
    ctrl = BmcController.query.get_or_404(cid)
    ctrl.approval_status = 'rejected'
    ctrl.enabled = False
    db.session.commit()
    return jsonify(ctrl.to_dict())


@oob_bp.route('/api/controllers/<int:cid>', methods=['PUT', 'PATCH'])
@login_required
def update_controller(cid):
    ctrl = BmcController.query.get_or_404(cid)
    d = request.get_json(force=True)
    if 'name' in d:
        ctrl.name = (d.get('name') or '').strip() or None
    if 'bmc_ip' in d:
        ctrl.bmc_ip = (d.get('bmc_ip') or '').strip()
    if 'bmc_port' in d:
        try:
            ctrl.bmc_port = _parse_port(d.get('bmc_port'), ctrl.bmc_port or 443)
        except (TypeError, ValueError) as e:
            return jsonify({'error': str(e)}), 400
    if 'use_ssl' in d:
        ctrl.use_ssl = _parse_bool(d.get('use_ssl'), ctrl.use_ssl if ctrl.use_ssl is not None else True)
    if 'verify_ssl' in d:
        ctrl.verify_ssl = _parse_bool(d.get('verify_ssl'), bool(ctrl.verify_ssl))
    if 'protocol' in d:
        ctrl.protocol = (d.get('protocol') or 'redfish').strip() or 'redfish'
    for field in ('bmc_mac', 'vendor', 'credential_id', 'enabled',
                  'device_id', 'approval_status'):
        if field in d:
            setattr(ctrl, field, d[field])
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': '保存失败：设备 ID 重复或非法'}), 409
    return jsonify(ctrl.to_dict())


@oob_bp.route('/api/controllers/<int:cid>', methods=['DELETE'])
@login_required
def delete_controller(cid):
    ctrl = BmcController.query.get_or_404(cid)
    db.session.delete(ctrl)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': '删除失败：存在关联记录'}), 409
    return jsonify({'ok': True})


@oob_bp.route('/api/drifts')
@login_required
def asset_drifts():
    """List open BMC/CMDB asset drift records."""
    status = request.args.get('status', 'open')
    limit = request.args.get('limit', 200, type=int)
    query = BmcAssetDrift.query.order_by(BmcAssetDrift.check_time.desc())
    if status != 'all':
        query = query.filter(BmcAssetDrift.status == status)
    rows = query.limit(min(limit, 500)).all()
    out = []
    for d in rows:
        item = d.to_dict()
        ctrl = d.controller
        item['controller_name'] = ctrl.name if ctrl else None
        item['bmc_ip'] = ctrl.bmc_ip if ctrl else None
        if ctrl and ctrl.device:
            item['device_name'] = ctrl.device.name
        else:
            item['device_name'] = None
        out.append(item)
    return jsonify(out)


@oob_bp.route('/api/drifts/<int:did>', methods=['PATCH'])
@login_required
def update_asset_drift(did):
    row = BmcAssetDrift.query.get_or_404(did)
    data = request.get_json(force=True, silent=True) or {}
    status = data.get('status')
    if status not in ('open', 'acknowledged', 'ignored', 'resolved'):
        return jsonify({'error': 'invalid status'}), 400
    row.status = status
    row.note = data.get('note', row.note)
    if status in ('resolved', 'ignored'):
        row.resolved_at = datetime.utcnow()
        row.resolved_by = current_user.username
    db.session.commit()
    return jsonify(row.to_dict())


@oob_bp.route('/api/controllers/<int:cid>/refresh')
@login_required
def refresh_controller(cid):
    """Trigger an on-demand poll for a single controller."""
    ctrl = BmcController.query.get_or_404(cid)
    from tasks.oob_poll import _poll_one
    _poll_one(db.session, ctrl)
    db.session.commit()
    return jsonify(ctrl.to_dict())


@oob_bp.route('/api/controllers/<int:cid>/sensors')
@login_required
def sensors(cid):
    BmcController.query.get_or_404(cid)
    limit = request.args.get('limit', 100, type=int)
    rows = (BmcSensor.query.filter_by(controller_id=cid)
            .order_by(BmcSensor.ts.desc()).limit(limit).all())
    states = (BmcSensorAlertState.query
              .filter_by(controller_id=cid).all())
    state_map = {(s.sensor_name or '', s.sensor_kind or 'sensor'): s
                 for s in states}
    required_strikes = max(1, int(current_app.config.get('OOB_SENSOR_ALERT_STRIKES', 2)))
    rule_ids = {r.threshold_rule_id for r in rows if r.threshold_rule_id}
    rule_map = {}
    if rule_ids:
        rule_map = {t.id: t.to_dict() for t in
                    BmcSensorThreshold.query.filter(
                        BmcSensorThreshold.id.in_(rule_ids)).all()}
    out = []
    for r in rows:
        d = r.to_dict()
        st = state_map.get((r.name or '', r.kind or 'sensor'))
        if st is None:
            d['alert_state'] = None
        else:
            d['alert_state'] = st.to_dict()
            d['alert_state']['required_strikes'] = required_strikes
        d['threshold_rule'] = rule_map.get(r.threshold_rule_id)
        out.append(d)
    return jsonify(out)


@oob_bp.route('/api/sensor-thresholds')
@login_required
def list_global_sensor_thresholds():
    rows = (BmcSensorThreshold.query
            .filter(BmcSensorThreshold.controller_id.is_(None))
            .order_by(BmcSensorThreshold.kind, BmcSensorThreshold.name,
                      BmcSensorThreshold.id).all())
    return jsonify([r.to_dict() for r in rows])


@oob_bp.route('/api/sensor-thresholds', methods=['POST'])
@login_required
def create_global_sensor_threshold():
    return _create_sensor_threshold(controller_id=None)


@oob_bp.route('/api/controllers/<int:cid>/sensor-thresholds')
@login_required
def list_controller_sensor_thresholds(cid):
    BmcController.query.get_or_404(cid)
    rows = (BmcSensorThreshold.query
            .filter(or_(BmcSensorThreshold.controller_id == cid,
                        BmcSensorThreshold.controller_id.is_(None)))
            .order_by(BmcSensorThreshold.kind, BmcSensorThreshold.name,
                      BmcSensorThreshold.id).all())
    return jsonify([r.to_dict() for r in rows])


@oob_bp.route('/api/controllers/<int:cid>/sensor-thresholds', methods=['POST'])
@login_required
def create_controller_sensor_threshold(cid):
    BmcController.query.get_or_404(cid)
    return _create_sensor_threshold(controller_id=cid)


@oob_bp.route('/api/sensor-thresholds/<int:tid>', methods=['PUT', 'PATCH'])
@login_required
def update_sensor_threshold(tid):
    row = BmcSensorThreshold.query.get_or_404(tid)
    d = request.get_json(force=True) or {}
    try:
        row.name = _empty_to_none(d.get('name'))
        row.kind = _empty_to_none(d.get('kind'))
        row.lower_warning = _parse_optional_float(d.get('lower_warning'))
        row.upper_warning = _parse_optional_float(d.get('upper_warning'))
        row.lower_critical = _parse_optional_float(d.get('lower_critical'))
        row.upper_critical = _parse_optional_float(d.get('upper_critical'))
        if 'enabled' in d:
            row.enabled = _parse_bool(d.get('enabled'), True)
        row.description = _empty_to_none(d.get('description'))
    except (TypeError, ValueError) as e:
        return jsonify({'error': str(e)}), 400
    db.session.commit()
    return jsonify(row.to_dict())


@oob_bp.route('/api/sensor-thresholds/<int:tid>', methods=['DELETE'])
@login_required
def delete_sensor_threshold(tid):
    row = BmcSensorThreshold.query.get_or_404(tid)
    db.session.delete(row)
    db.session.commit()
    return jsonify({'ok': True})


@oob_bp.route('/api/controllers/<int:cid>/power', methods=['POST'])
@login_required
def power(cid):
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'error': 'no credential configured'}), 400
    action = (request.get_json(force=True) or {}).get('action')
    if action not in RESET_TYPES:
        return jsonify({'error': 'invalid action', 'valid': list(RESET_TYPES)}), 400

    mgr = OobManager(ctrl, ctrl.credential)
    try:
        result = mgr.power_action(action)
    except OobError as e:
        db.session.add(BmcPowerLog(
            controller_id=cid, user_id=current_user.id,
            action=action, result='failed', message=str(e)))
        db.session.commit()
        return jsonify({'error': str(e)}), 502

    db.session.add(BmcPowerLog(
        controller_id=cid, user_id=current_user.id,
        action=action, result='success'))
    db.session.commit()
    return jsonify(result)


@oob_bp.route('/api/controllers/<int:cid>/logs')
@login_required
def power_logs(cid):
    rows = (BmcPowerLog.query.filter_by(controller_id=cid)
            .order_by(BmcPowerLog.created_at.desc()).limit(200).all())
    return jsonify([r.to_dict() for r in rows])


# ------------------------------------------------------------------ 固件升级（对标 DCOS「固件升级」）
@oob_bp.route('/firmware')
@login_required
def firmware_page():
    """固件升级页面：列出所有控制器，支持单台/批量发起升级。"""
    return render_template('oob/firmware.html')


@oob_bp.route('/api/firmware/controllers')
@login_required
def firmware_controllers():
    rows = BmcController.query.order_by(BmcController.name).all()
    return jsonify([
        {'id': c.id, 'name': c.name, 'bmc_ip': c.bmc_ip,
         'vendor': c.vendor, 'enabled': c.enabled,
         'has_credential': bool(c.credential_id)}
        for c in rows
    ])


@oob_bp.route('/api/firmware/<int:cid>/inventory')
@login_required
def firmware_inventory(cid):
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'error': 'no credential configured'}), 400
    mgr = OobManager(ctrl, ctrl.credential)
    try:
        service = mgr.get_update_service()
        items = mgr.get_firmware_inventory()
    except OobError as e:
        return jsonify({'error': str(e)}), 502
    return jsonify({'controller': ctrl.name, 'update_service': service,
                    'inventory': items})


@oob_bp.route('/api/firmware/<int:cid>/upgrade', methods=['POST'])
@login_required
def firmware_upgrade(cid):
    """为单台控制器发起固件升级（SimpleUpdate）。批量由前端逐台调用。"""
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'error': 'no credential configured'}), 400
    d = request.get_json(force=True, silent=True) or {}
    image_url = (d.get('image_url') or '').strip()
    if not image_url:
        return jsonify({'error': 'image_url required'}), 400
    protocol = d.get('transfer_protocol', 'HTTP')
    mgr = OobManager(ctrl, ctrl.credential)
    try:
        res = mgr.update_firmware(image_url, transfer_protocol=protocol)
    except OobError as e:
        job = BmcFirmwareJob(controller_id=cid, image_url=image_url,
                             transfer_protocol=protocol, status='failed',
                             error=str(e), operator=current_user.username)
        db.session.add(job)
        db.session.commit()
        return jsonify({'error': str(e)}), 502
    job = BmcFirmwareJob(controller_id=cid, image_url=image_url,
                         transfer_protocol=protocol, status='submitted',
                         task_ref=str(res.get('task')) if res.get('task') else None,
                         operator=current_user.username)
    db.session.add(job)
    db.session.commit()
    return jsonify({'job': job.to_dict(), 'raw': res.get('raw')}), 201


@oob_bp.route('/api/firmware/jobs')
@login_required
def firmware_jobs():
    rows = BmcFirmwareJob.query.order_by(BmcFirmwareJob.created_at.desc()).limit(100).all()
    out = []
    for j in rows:
        d = j.to_dict()
        d['controller_name'] = j.controller.name if j.controller else None
        out.append(d)
    return jsonify(out)


@oob_bp.route('/api/firmware/jobs/<int:jid>/refresh', methods=['POST'])
@login_required
def firmware_job_refresh(jid):
    """On-demand refresh of a firmware job's status from the BMC Task."""
    job = BmcFirmwareJob.query.get_or_404(jid)
    ctrl = job.controller
    if ctrl is None or not ctrl.credential:
        return jsonify({'error': 'no controller or credential'}), 400
    if not job.task_ref:
        return jsonify({'job': job.to_dict(),
                        'note': 'no task_ref to track, verify manually'}), 200
    mgr = OobManager(ctrl, ctrl.credential)
    try:
        st = mgr.get_task_status(job.task_ref)
    except OobError as e:
        return jsonify({'error': str(e)}), 502
    if st.get('failed'):
        job.status = 'failed'
        job.error = st.get('message') or ('task state=%s' % st.get('state'))
        job.finished_at = datetime.now()
    elif st.get('completed'):
        job.status = 'success'
        job.error = None
        job.finished_at = datetime.now()
    else:
        job.status = 'running'
    db.session.commit()
    out = job.to_dict()
    out['task'] = st
    return jsonify({'job': out})


# ------------------------------------------------------------------ BIOS 模板批量下发（对标 DCOS「BIOS 模板」）
@oob_bp.route('/bios')
@login_required
def bios_page():
    return render_template('oob/bios.html')


@oob_bp.route('/api/bios/<int:cid>/attributes')
@login_required
def bios_attributes(cid):
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'error': 'no credential configured'}), 400
    mgr = OobManager(ctrl, ctrl.credential)
    try:
        data = mgr.get_bios_attributes()
    except OobError as e:
        return jsonify({'error': str(e)}), 502
    data['controller'] = ctrl.name
    return jsonify(data)


@oob_bp.route('/api/bios/templates', methods=['POST'])
@login_required
def bios_template_create():
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    attrs = d.get('attributes') or {}
    if not isinstance(attrs, dict) or not attrs:
        return jsonify({'error': 'attributes must be a non-empty object'}), 400
    if BiosTemplate.query.filter_by(name=name).first():
        return jsonify({'error': 'template name already exists'}), 409
    tpl = BiosTemplate(
        name=name, vendor=d.get('vendor'),
        description=d.get('description'),
        attributes_json=json.dumps(attrs, ensure_ascii=False),
        source_controller_id=d.get('source_controller_id'),
        creator=current_user.username)
    db.session.add(tpl)
    db.session.commit()
    return jsonify(tpl.to_dict()), 201


@oob_bp.route('/api/bios/templates')
@login_required
def bios_template_list():
    rows = BiosTemplate.query.order_by(BiosTemplate.name).all()
    return jsonify([r.to_dict() for r in rows])


@oob_bp.route('/api/bios/templates/<int:tid>')
@login_required
def bios_template_detail(tid):
    tpl = BiosTemplate.query.get_or_404(tid)
    out = tpl.to_dict()
    out['attributes'] = tpl.get_attributes()
    return jsonify(out)


@oob_bp.route('/api/bios/templates/<int:tid>', methods=['DELETE'])
@login_required
def bios_template_delete(tid):
    tpl = BiosTemplate.query.get_or_404(tid)
    db.session.delete(tpl)
    db.session.commit()
    return jsonify({'ok': True})


@oob_bp.route('/api/bios/templates/<int:tid>/apply', methods=['POST'])
@login_required
def bios_template_apply(tid):
    """将模板属性批量下发到多台控制器（逐台 PATCH，返回每台结果）。"""
    tpl = BiosTemplate.query.get_or_404(tid)
    d = request.get_json(force=True, silent=True) or {}
    controller_ids = d.get('controller_ids') or []
    if not isinstance(controller_ids, list) or not controller_ids:
        return jsonify({'error': 'controller_ids required'}), 400
    attrs = tpl.get_attributes()
    results = []
    for cid in controller_ids:
        ctrl = BmcController.query.get(cid)
        if not ctrl:
            results.append({'controller_id': cid, 'status': 'skipped',
                            'message': 'controller not found'})
            continue
        if not ctrl.credential:
            results.append({'controller_id': cid, 'name': ctrl.name,
                            'status': 'failed', 'message': 'no credential'})
            continue
        mgr = OobManager(ctrl, ctrl.credential)
        try:
            r = mgr.set_bios_attributes(attrs)
            if r['failed']:
                results.append({'controller_id': cid, 'name': ctrl.name,
                                'status': 'failed', 'detail': r})
            else:
                results.append({'controller_id': cid, 'name': ctrl.name,
                                'status': 'success', 'detail': r})
        except OobError as e:
            results.append({'controller_id': cid, 'name': ctrl.name,
                            'status': 'failed', 'message': str(e)})
    return jsonify({'template': tpl.name, 'results': results})

@oob_bp.route('/api/controllers/<int:cid>/health')
@login_required
def controller_health(cid):
    """Live Redfish aggregate health + power consumption."""
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'error': 'no credential configured'}), 400
    mgr = OobManager(ctrl, ctrl.credential)
    try:
        return jsonify(mgr.get_health())
    except OobError as e:
        return jsonify({'error': str(e)}), 502


@oob_bp.route('/api/controllers/<int:cid>/network')
@login_required
def controller_network(cid):
    """Live iDRAC host NIC inventory (MAC / speed / status)."""
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'error': 'no credential configured'}), 400
    mgr = OobManager(ctrl, ctrl.credential)
    try:
        return jsonify(mgr.get_network())
    except OobError as e:
        return jsonify({'error': str(e)}), 502
@oob_bp.route('/api/controllers/<int:cid>/bios')
@login_required
def controller_bios(cid):
    """Live iDRAC BIOS attribute inventory (current + pending)."""
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'error': 'no credential configured'}), 400
    mgr = OobManager(ctrl, ctrl.credential)
    try:
        return jsonify(mgr.get_bios_attributes())
    except OobError as e:
        return jsonify({'error': str(e)}), 502


@oob_bp.route('/api/controllers/<int:cid>/sel')
@login_required
def controller_logs(cid):
    """Live iDRAC LogServices entries (default SEL).

    路径使用 /sel 而非 /logs：/logs 已被电源操作审计日志（power_logs）占用，
    两条同路径路由会按注册顺序遮蔽，导致本接口此前不可达。
    """
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'error': 'no credential configured'}), 400
    log_type = request.args.get('type', 'sel')
    limit = min(request.args.get('limit', 100, type=int), 500)
    mgr = OobManager(ctrl, ctrl.credential)
    try:
        return jsonify(mgr.get_logs(log_type=log_type, max_entries=limit))
    except OobError as e:
        return jsonify({'error': str(e)}), 502
@oob_bp.route('/api/controllers/<int:cid>/events')
@login_required
def event_logs(cid):
    """Persisted BMC event logs (from SEL polling)."""
    BmcController.query.get_or_404(cid)
    limit = min(request.args.get('limit', 100, type=int), 500)
    severity = request.args.get('severity')
    q = BmcEventLog.query.filter_by(controller_id=cid)
    if severity:
        q = q.filter(BmcEventLog.severity.ilike('%' + severity + '%'))
    rows = (q.order_by(BmcEventLog.log_time.desc())
            .limit(limit).all())
    return jsonify([r.to_dict() for r in rows])


@oob_bp.route('/api/events/<int:eid>/ack', methods=['POST'])
@login_required
def ack_event_log(eid):
    """Mark a persisted BMC event log as handled (alert acknowledged)."""
    row = BmcEventLog.query.get_or_404(eid)
    row.alerted = True
    db.session.commit()
    return jsonify(row.to_dict())


# ------------------------------------------------------------------ 概览看板（对标 DCOS 总览）
@oob_bp.route('/overview')
@login_required
def overview_page():
    return render_template('oob/overview.html')


@oob_bp.route('/api/overview')
@login_required
def overview_stats():
    """Fleet-level aggregate stats for the overview dashboard."""
    controllers = BmcController.query.all()
    total = len(controllers)
    by_power = Counter((c.power_state or 'Unknown') for c in controllers)
    by_vendor = Counter((c.vendor or 'unknown') for c in controllers)
    enabled = sum(1 for c in controllers if c.enabled)
    with_cred = sum(1 for c in controllers if c.credential_id)
    polled = sum(1 for c in controllers if c.last_poll)

    # 每台控制器最新一条 power / temperature 读数（用于汇总功耗与温度分布）
    def latest_reading(kind):
        rows = db.session.execute(text(
            "SELECT s.controller_id, s.reading FROM bmc_sensors s "
            "WHERE s.kind=:k AND s.ts=(SELECT MAX(ts) FROM bmc_sensors "
            "WHERE controller_id=s.controller_id AND kind=:k)"
        ), {'k': kind}).fetchall()
        return {r[0]: r[1] for r in rows if r[1] is not None}

    power_map = latest_reading('power')
    temp_map = latest_reading('temperature')
    total_power = round(sum(power_map.values()), 1)
    temps = list(temp_map.values())
    avg_temp = round(sum(temps) / len(temps), 1) if temps else None
    max_temp = round(max(temps), 1) if temps else None

    # 最新传感器状态统计（warning/critical）
    sensor_stats = db.session.execute(text(
        "SELECT status, COUNT(*) FROM bmc_sensors WHERE ts=(SELECT MAX(ts) FROM bmc_sensors s2 WHERE s2.controller_id=bmc_sensors.controller_id AND s2.kind=bmc_sensors.kind) GROUP BY status"
    )).fetchall()
    sensor_status = {r[0]: r[1] for r in sensor_stats}

    # 近期未确认 SEL 严重事件数
    pending_sel = db.session.execute(text(
        "SELECT COUNT(*) FROM bmc_event_logs e JOIN bmc_controllers c "
        "ON c.id=e.controller_id WHERE LOWER(e.severity) IN ('critical','emergency') "
        "AND e.alerted=0"
    )).scalar() or 0


    # P1/P2 sensor alert debounce state aggregation
    sensor_active_alerts = db.session.execute(text(
        "SELECT COUNT(*) FROM alert_events "
        "WHERE status='active' AND metric_type LIKE 'bmc_%'"
    )).scalar() or 0
    sensor_debounce_pending = db.session.execute(text(
        "SELECT COUNT(*) FROM bmc_sensor_alert_states "
        "WHERE consecutive_strikes > 0 "
        "AND (alert_id IS NULL OR alert_id = 0)"
    )).scalar() or 0

    return jsonify({
        'total': total,
        'enabled': enabled,
        'with_credential': with_cred,
        'polled': polled,
        'by_power': dict(by_power),
        'by_vendor': dict(by_vendor),
        'sensor_active_alerts': sensor_active_alerts,
        'sensor_debounce_pending': sensor_debounce_pending,
        'total_power_watts': total_power,
        'avg_temp': avg_temp,
        'max_temp': max_temp,
        'sensor_status': sensor_status,
        'pending_sel_critical': pending_sel,
    })


# ------------------------------------------------------------------ 配置备份 / 恢复（对标 DCOS「服务器备份」）
@oob_bp.route('/backup')
@login_required
def backup_page():
    controllers = BmcController.query.order_by(BmcController.name).all()
    return render_template('oob/backup.html', controllers=controllers)


@oob_bp.route('/api/controllers/<int:cid>/backup', methods=['POST'])
@login_required
def create_backup(cid):
    ctrl = BmcController.query.get_or_404(cid)
    if not ctrl.credential:
        return jsonify({'error': 'no credential configured'}), 400
    mgr = OobManager(ctrl, ctrl.credential)
    snap = mgr.get_config_snapshot()
    if not snap or not snap.get('system') and not snap.get('bios_attributes'):
        return jsonify({'error': '无法获取 BMC 配置（Redfish 不可达或凭据无效）'}), 502
    blob = json.dumps(snap, ensure_ascii=False, default=str)
    checksum = hashlib.sha256(blob.encode('utf-8')).hexdigest()
    name = (request.get_json(force=True, silent=True) or {}).get('name') or (
        'backup-%s-%s' % (ctrl.bmc_ip or cid,
                          (ctrl.last_poll or datetime.now()).strftime('%Y%m%d%H%M%S')))
    bk = BmcConfigBackup(
        controller_id=cid,
        name=name,
        config_json=blob,
        checksum=checksum,
        operator=getattr(current_user, 'username', str(current_user.id)),
    )
    db.session.add(bk)
    db.session.commit()
    return jsonify(bk.to_dict()), 201


@oob_bp.route('/api/backups')
@login_required
def list_backups():
    rows = (BmcConfigBackup.query
            .join(BmcController, BmcController.id == BmcConfigBackup.controller_id)
            .order_by(BmcConfigBackup.created_at.desc()).limit(500).all())
    out = []
    for b in rows:
        d = b.to_dict()
        d['controller_name'] = b.controller.name if b.controller else None
        d['bmc_ip'] = b.controller.bmc_ip if b.controller else None
        out.append(d)
    return jsonify(out)


@oob_bp.route('/api/controllers/<int:cid>/backups')
@login_required
def list_controller_backups(cid):
    rows = (BmcConfigBackup.query.filter_by(controller_id=cid)
            .order_by(BmcConfigBackup.created_at.desc()).all())
    return jsonify([r.to_dict() for r in rows])


@oob_bp.route('/api/backups/<int:bid>/download')
@login_required
def download_backup(bid):
    bk = BmcConfigBackup.query.get_or_404(bid)
    cfg = bk.get_config()
    data = json.dumps(cfg, ensure_ascii=False, indent=2, default=str)
    resp = make_response(data)
    resp.headers['Content-Type'] = 'application/json; charset=utf-8'
    fname = 'bmc_backup_%s.json' % bid
    resp.headers['Content-Disposition'] = "attachment; filename=%s" % fname
    return resp


@oob_bp.route('/api/backups/<int:bid>/restore', methods=['POST'])
@login_required
def restore_backup(bid):
    bk = BmcConfigBackup.query.get_or_404(bid)
    ctrl = bk.controller
    if ctrl is None or not ctrl.credential:
        return jsonify({'error': '控制器或凭据缺失'}), 400
    mgr = OobManager(ctrl, ctrl.credential)
    try:
        result = mgr.restore_config(bk.get_config())
    except OobError as e:
        return jsonify({'error': str(e)}), 502
    return jsonify({'result': result})


# ------------------------------------------------------------------ SEL 事件日志导出（对标 DCOS「日志下载」）
@oob_bp.route('/api/controllers/<int:cid>/events/export')
@login_required
def export_events(cid):
    BmcController.query.get_or_404(cid)
    fmt = (request.args.get('format') or 'csv').lower()
    limit = min(request.args.get('limit', 1000, type=int), 5000)
    severity = request.args.get('severity')
    q = BmcEventLog.query.filter_by(controller_id=cid)
    if severity:
        q = q.filter(BmcEventLog.severity.ilike('%' + severity + '%'))
    rows = q.order_by(BmcEventLog.log_time.desc()).limit(limit).all()

    if fmt == 'json':
        data = json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=2)
        resp = make_response(data)
        resp.headers['Content-Type'] = 'application/json; charset=utf-8'
        resp.headers['Content-Disposition'] = "attachment; filename=bmc_sel_%s.json" % cid
        return resp

    # CSV
    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['id', 'entry_type', 'severity', 'log_time', 'message_id',
                    'sensor_type', 'event_id', 'message', 'alerted'])
    for r in rows:
        writer.writerow([r.id, r.entry_type, r.severity,
                         r.log_time.isoformat() if r.log_time else '',
                         r.message_id, r.sensor_type, r.event_id,
                         (r.message or '').replace('\n', ' '), r.alerted])
    resp = make_response(buf.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = "attachment; filename=bmc_sel_%s.csv" % cid
    return resp


# ------------------------------------------------------------------ 批量电源操作（对标 DCOS 批量任务）
@oob_bp.route('/api/controllers/batch-power', methods=['POST'])
@login_required
def batch_power():
    d = request.get_json(force=True) or {}
    ids = d.get('ids') or []
    action = d.get('action')
    if action not in RESET_TYPES:
        return jsonify({'error': 'invalid action', 'valid': list(RESET_TYPES)}), 400
    if not isinstance(ids, list) or not ids:
        return jsonify({'error': 'ids required'}), 400
    results = []
    for cid in ids:
        ctrl = BmcController.query.get(cid)
        if ctrl is None:
            results.append({'id': cid, 'ok': False, 'error': 'not found'})
            continue
        if not ctrl.credential:
            results.append({'id': cid, 'ok': False, 'error': 'no credential'})
            db.session.add(BmcPowerLog(controller_id=cid, user_id=current_user.id,
                                       action=action, result='failed',
                                       message='no credential'))
            continue
        mgr = OobManager(ctrl, ctrl.credential)
        try:
            mgr.power_action(action)
            db.session.add(BmcPowerLog(controller_id=cid, user_id=current_user.id,
                                       action=action, result='success'))
            results.append({'id': cid, 'ok': True})
        except OobError as e:
            db.session.add(BmcPowerLog(controller_id=cid, user_id=current_user.id,
                                       action=action, result='failed', message=str(e)))
            results.append({'id': cid, 'ok': False, 'error': str(e)})
    db.session.commit()
    return jsonify({'results': results})


# ------------------------------------------------------------------ 告警升级联动（SEL/iDRAC 带外）
@oob_bp.route('/escalations')
@login_required
def escalations_page():
    """升级策略管理页：策略列表 + 最近升级日志 + 待升级活跃 SEL 告警。"""
    from models.models import AlertEscalation, AlertEscalationLog, AlertEvent
    try:
        policies = (AlertEscalation.query
                    .order_by(AlertEscalation.original_severity, AlertEscalation.name).all())
        logs = (AlertEscalationLog.query
                .order_by(AlertEscalationLog.escalated_at.desc()).limit(100).all())
        policy_names = {p.id: p.name for p in policies}
    except Exception:
        # 未迁移时优雅降级（schema 尚无新列）
        policies, logs, policy_names = [], [], {}
    pending = (AlertEvent.query
               .filter(AlertEvent.status == 'active',
                       AlertEvent.suppressed.isnot(True),
                       AlertEvent.acknowledged_at.is_(None),
                       AlertEvent.metric_type == 'bmc_sel').count())
    return render_template('oob/escalations.html',
                           policies=policies, logs=logs, pending_sel=pending,
                           policy_names=policy_names)


@oob_bp.route('/api/escalations')
@login_required
def list_escalations():
    from models.models import AlertEscalation
    try:
        policies = (AlertEscalation.query
                    .order_by(AlertEscalation.original_severity, AlertEscalation.name).all())
        return jsonify([p.to_dict() for p in policies])
    except Exception:
        return jsonify([])


@oob_bp.route('/api/escalations/logs')
@login_required
def list_escalation_logs():
    from models.models import AlertEscalationLog, AlertEscalation
    limit = min(request.args.get('limit', 100, type=int), 500)
    try:
        rows = (AlertEscalationLog.query
                .order_by(AlertEscalationLog.escalated_at.desc()).limit(limit).all())
        policies = {p.id: p.name for p in AlertEscalation.query.all()}
    except Exception:
        return jsonify([])
    out = []
    for r in rows:
        d = {
            'id': r.id, 'alert_id': r.alert_id, 'policy_id': r.policy_id,
            'policy': policies.get(r.policy_id, r.policy_id),
            'level': r.level, 'from_severity': r.from_severity,
            'to_severity': r.to_severity, 'channel': r.channel,
            'target': r.target,
            'message': (r.message or '')[:500],
            'escalated_at': r.escalated_at.isoformat() if r.escalated_at else None,
        }
        out.append(d)
    return jsonify(out)


@oob_bp.route('/api/escalations', methods=['POST'])
@login_required
def create_escalation():
    from models.models import AlertEscalation
    from utils.audit import log_audit
    d = request.get_json(force=True) or {}
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    if not (d.get('original_severity') or '').strip():
        return jsonify({'error': 'original_severity is required'}), 400
    p = AlertEscalation(
        name=name,
        description=d.get('description'),
        original_severity=(d.get('original_severity') or '').strip(),
        escalate_after=int(d.get('escalate_after', 300)),
        escalate_if_unacknowledged=bool(d.get('escalate_if_unacknowledged', True)),
        target_severity=(d.get('target_severity') or d.get('original_severity') or 'critical'),
        metric_type=(d.get('metric_type') or '').strip() or None,
        max_escalations=int(d.get('max_escalations', 3)),
        repeat_interval=int(d.get('repeat_interval', 0)),
        escalation_message=d.get('escalation_message'),
        auto_create_work_order=bool(d.get('auto_create_work_order', False)),
        enabled=bool(d.get('enabled', True)),
    )
    p.set_target_users(d.get('target_users') or [])
    p.set_target_groups(d.get('target_groups') or [])
    p.set_target_actions(d.get('target_actions') or [])
    db.session.add(p)
    db.session.commit()
    log_audit('create', 'alert_escalation', p.id, '创建升级策略: %s' % name,
              details={'metric_type': p.metric_type,
                       'original_severity': p.original_severity,
                       'escalate_after': p.escalate_after})
    return jsonify(p.to_dict()), 201


@oob_bp.route('/api/escalations/<int:pid>/toggle', methods=['POST'])
@login_required
def toggle_escalation(pid):
    from models.models import AlertEscalation
    from utils.audit import log_audit
    p = AlertEscalation.query.get_or_404(pid)
    p.enabled = not p.enabled
    db.session.commit()
    log_audit('update', 'alert_escalation', pid, '%s 升级策略: %s' % (
        '启用' if p.enabled else '停用', p.name))
    return jsonify(p.to_dict())


@oob_bp.route('/api/escalations/<int:pid>', methods=['DELETE'])
@login_required
def delete_escalation(pid):
    from models.models import AlertEscalation
    from utils.audit import log_audit
    p = AlertEscalation.query.get_or_404(pid)
    name = p.name
    db.session.delete(p)
    db.session.commit()
    log_audit('delete', 'alert_escalation', pid, '删除升级策略: %s' % name)
    return jsonify({'ok': True})


@oob_bp.route('/api/escalations/run', methods=['POST'])
@login_required
def run_escalation_manual():
    """立即执行一次升级扫描（手动触发）。"""
    from services.escalation_service import run_escalations
    from utils.audit import log_audit
    performed = run_escalations()
    log_audit('execute', 'alert_escalation', 0, '手动触发升级扫描',
              details={'performed': len(performed)})
    return jsonify({'ok': True, 'performed': performed})
