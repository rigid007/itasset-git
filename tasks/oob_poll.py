# tasks/oob_poll.py
"""Periodic BMC poll: refresh power state / firmware, persist sensor readings,
write back Device temperature / power fields and raise alerts on thresholds."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_

from extensions import get_bg_session
from models.oob_models import (BmcController, BmcSensor, BmcSensorAlertState,
                               BmcSensorThreshold, BmcEventLog, BmcFirmwareJob,
                               BmcAssetDrift)
from models.models import AlertEvent, AlertRule
from services.oob_manager import OobManager, OobError
from utils.event_correlation import process_alert_correlation

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def poll_all_bmc(app=None):
    """Poll every enabled BMC. Called by the scheduler (with app) or manually."""
    if app is not None:
        with app.app_context():
            _poll_all_bmc_impl()
    else:
        _poll_all_bmc_impl()


def _poll_all_bmc_impl():
    try:
        from flask import current_app
        if not current_app.config.get('OOB_ENABLED', True):
            return
    except RuntimeError:
        pass

    # 1) 默认 SEL 关联规则（一次性）
    setup = get_bg_session()
    try:
        ensure_default_sel_rules(setup)
        setup.commit()
    finally:
        setup.close()

    # 2) 收集启用的控制器 id
    s = get_bg_session()
    try:
        ctrl_ids = [cid for (cid,) in
                    s.query(BmcController.id)
                    .filter(BmcController.enabled.is_(True),
                            BmcController.bmc_ip.isnot(None),
                            BmcController.bmc_ip != '')
                    .all()]
    finally:
        s.close()

    if not ctrl_ids:
        return

    # 3) 并发轮询：每台控制器用独立 bg session（SQLAlchemy session 非线程安全，
    #    不能在多线程间共享），按 OOB_POLL_WORKERS 控制并发度
    with ThreadPoolExecutor(max_workers=_poll_workers()) as ex:
        list(ex.map(_poll_controller_worker, ctrl_ids))


def _poll_workers():
    try:
        from flask import current_app
        return int(current_app.config.get('OOB_POLL_WORKERS', 8))
    except RuntimeError:
        return 8


def _poll_controller_worker(cid):
    s = get_bg_session()
    try:
        ctrl = s.get(BmcController, cid)
        if ctrl is None:
            return
        try:
            _poll_one(s, ctrl)
        except OobError as e:
            ctrl.last_error = str(e)
            logger.warning('OOB poll failed for %s: %s', ctrl.bmc_ip, e)
        except Exception as e:
            ctrl.last_error = str(e)
            logger.exception('OOB poll unexpected error for %s', ctrl.bmc_ip)
        s.commit()
    finally:
        s.close()


def _clean_asset_value(value):
    """Normalize a Redfish/IPMI string for comparison."""
    if value is None:
        return ''
    text = str(value).strip()
    if text.lower() in ('none', 'unknown', 'n/a', 'not available', 'not specified'):
        return ''
    return text


def _record_asset_drift(session, ctrl, dev, field_name, expected, discovered, severity='warning'):
    """Persist one open drift record, reusing the latest open record if unchanged."""
    expected = _clean_asset_value(expected)
    discovered = _clean_asset_value(discovered)
    if expected and discovered and expected.lower() == discovered.lower():
        return None

    existing = (session.query(BmcAssetDrift)
                .filter(BmcAssetDrift.controller_id == ctrl.id,
                        BmcAssetDrift.field_name == field_name,
                        BmcAssetDrift.status == 'open')
                .order_by(BmcAssetDrift.id.desc())
                .first())
    if existing and existing.discovered_value == discovered:
        existing.expected_value = expected
        existing.device_id = dev.id if dev else None
        existing.check_time = _now()
        return existing

    row = BmcAssetDrift(
        controller_id=ctrl.id,
        device_id=dev.id if dev else None,
        field_name=field_name,
        expected_value=expected or None,
        discovered_value=discovered or None,
        severity=severity,
        status='open',
        source='redfish_poll',
        check_time=_now(),
    )
    session.add(row)
    return row


def _resolve_asset_drift_if_match(session, ctrl, dev, field_name, expected, discovered):
    """Close open drift records once CMDB and BMC values match again."""
    expected = _clean_asset_value(expected)
    discovered = _clean_asset_value(discovered)
    if not (expected and discovered) or expected.lower() != discovered.lower():
        return
    rows = (session.query(BmcAssetDrift)
            .filter(BmcAssetDrift.controller_id == ctrl.id,
                    BmcAssetDrift.field_name == field_name,
                    BmcAssetDrift.status == 'open')
            .all())
    for row in rows:
        row.status = 'resolved'
        row.resolved_at = _now()
        row.resolved_by = 'redfish_poll'
        row.note = (row.note or '') + '\n[auto] BMC value now matches CMDB'


def _reconcile_bmc_asset(session, ctrl, dev, system):
    """Write back discovered fields when CMDB is blank, otherwise record drift."""
    discovered_serial = _clean_asset_value(system.get('SerialNumber'))
    discovered_model = _clean_asset_value(system.get('Model'))
    discovered_manufacturer = _clean_asset_value(system.get('Manufacturer'))
    discovered_bios = _clean_asset_value(system.get('BiosVersion'))

    expected_serial = _clean_asset_value(dev.serial_number or ctrl.serial_number) if dev else _clean_asset_value(ctrl.serial_number)
    expected_model = _clean_asset_value(dev.model or ctrl.model) if dev else _clean_asset_value(ctrl.model)
    expected_manufacturer = _clean_asset_value(dev.brand or dev.manufacturer) if dev else _clean_asset_value(ctrl.vendor)
    expected_bios = _clean_asset_value(ctrl.bios_version or '')

    # Always refresh controller-level inventory fields when BMC reports them.
    if discovered_serial:
        ctrl.serial_number = discovered_serial
    if discovered_model:
        ctrl.model = discovered_model
    if discovered_manufacturer and not ctrl.vendor:
        ctrl.vendor = discovered_manufacturer
    if discovered_bios:
        ctrl.bios_version = discovered_bios

    if dev is None:
        return

    if discovered_serial and not expected_serial:
        dev.serial_number = discovered_serial
    elif discovered_serial and expected_serial and expected_serial.lower() != discovered_serial.lower():
        _record_asset_drift(session, ctrl, dev, 'serial_number', expected_serial, discovered_serial, severity='critical')

    if discovered_model and not expected_model:
        dev.model = discovered_model
    elif discovered_model and expected_model and expected_model.lower() != discovered_model.lower():
        _record_asset_drift(session, ctrl, dev, 'model', expected_model, discovered_model, severity='warning')

    if discovered_manufacturer and not expected_manufacturer:
        if not dev.brand and not dev.manufacturer:
            dev.brand = discovered_manufacturer
    elif discovered_manufacturer and expected_manufacturer and expected_manufacturer.lower() != discovered_manufacturer.lower():
        _record_asset_drift(session, ctrl, dev, 'manufacturer', expected_manufacturer, discovered_manufacturer, severity='warning')

    if discovered_bios and not expected_bios:
        ctrl.bios_version = discovered_bios
    elif discovered_bios and expected_bios and expected_bios.lower() != discovered_bios.lower():
        _record_asset_drift(session, ctrl, dev, 'bios_version', expected_bios, discovered_bios, severity='warning')

    # If an earlier mismatch was later corrected in CMDB or on the BMC, close the
    # still-open drift automatically instead of leaving stale audit rows forever.
    _resolve_asset_drift_if_match(session, ctrl, dev, 'serial_number',
                                  dev.serial_number if dev else ctrl.serial_number,
                                  discovered_serial)
    _resolve_asset_drift_if_match(session, ctrl, dev, 'model',
                                  dev.model if dev else ctrl.model,
                                  discovered_model)
    _resolve_asset_drift_if_match(session, ctrl, dev, 'manufacturer',
                                  (dev.brand or dev.manufacturer) if dev else ctrl.vendor,
                                  discovered_manufacturer)
    _resolve_asset_drift_if_match(session, ctrl, dev, 'bios_version',
                                  ctrl.bios_version, discovered_bios)


def _poll_one(session, ctrl):
    if not ctrl.credential:
        ctrl.last_error = 'no credential configured'
        return

    mgr = OobManager(ctrl, ctrl.credential)

    # 1) system / power state (Redfish, IPMI fallback)
    try:
        system = mgr.get_system()
    except OobError:
        system = mgr.get_system_ipmi()

    ctrl.power_state = system.get('PowerState') or 'Unknown'
    ctrl.bios_version = system.get('BiosVersion')
    ctrl.model = system.get('Model')
    ctrl.serial_number = system.get('SerialNumber')
    ctrl.last_poll = _now()
    ctrl.last_error = None

    dev = ctrl.device
    if dev is not None:
        if system.get('PowerState'):
            dev.power_status = system.get('PowerState')
        dev.last_checked = _now()

    # 1.5) reconcile discovered BMC fields back to CMDB and record drift
    _reconcile_bmc_asset(session, ctrl, dev, system)

    # 2) sensors (best-effort: a failing sensor endpoint should not prevent
    #    event-log polling or controller status updates)
    now = _now()
    try:
        sensor_rows = mgr.get_sensors()
    except OobError as exc:
        ctrl.last_error = 'sensors read failed: %s' % exc
        logger.warning('OOB sensor poll failed for %s: %s', ctrl.bmc_ip, exc)
        sensor_rows = []
    threshold_rows = _load_sensor_thresholds(session, ctrl.id)
    for raw_s in sensor_rows:
        s = dict(raw_s)
        threshold = _resolve_sensor_threshold(threshold_rows, s.get('name'), s.get('kind'))
        _apply_sensor_threshold(s, threshold)
        sensor = BmcSensor(
            controller_id=ctrl.id,
            name=s.get('name'),
            kind=s.get('kind'),
            reading=s.get('reading'),
            unit=s.get('unit'),
            status=_normalize_sensor_status(s),
            lower_warning=s.get('lower_warning'),
            upper_warning=s.get('upper_warning'),
            lower_critical=s.get('lower_critical'),
            upper_critical=s.get('upper_critical'),
            threshold_rule_id=threshold.id if threshold is not None else None,
            threshold_source=_sensor_threshold_source(s, threshold),
            threshold_breach=_sensor_breach(s),
            ts=now,
        )
        session.add(sensor)
        session.flush()
        if dev is not None:
            if sensor.kind == 'temperature' and sensor.reading is not None:
                dev.temperature = sensor.reading
            if sensor.kind == 'power' and sensor.reading is not None:
                dev.power_consumption = sensor.reading
        _evaluate_sensor_alert(session, dev, sensor, ctrl)

    # 3) event logs (SEL / Lifecycle) persistence + alert linkage
    try:
        _poll_event_logs(session, ctrl, mgr, dev)
    except Exception as exc:
        # _poll_event_logs already catches Redfish/OobError; this guard keeps a
        # persistence bug in one log from failing the whole BMC poll.
        ctrl.last_error = (ctrl.last_error or '') + '; event log poll failed: %s' % exc
        logger.exception('OOB event log poll failed for %s', ctrl.bmc_ip)


def _sensor_config():
    """Return sensor alert debounce settings from Flask config.

    Safe to call inside an application context; when no context is available
    (e.g. a direct unit test) defaults are still returned.
    """
    try:
        from flask import current_app
        return {
            'window_minutes': int(current_app.config.get('OOB_SENSOR_ALERT_WINDOW_MINUTES', 15)),
            'strikes': max(1, int(current_app.config.get('OOB_SENSOR_ALERT_STRIKES', 2))),
        }
    except RuntimeError:
        return {'window_minutes': 15, 'strikes': 2}


def _load_sensor_thresholds(session, controller_id):
    """Return enabled controller-specific and global threshold override rows."""
    return (session.query(BmcSensorThreshold)
            .filter(or_(BmcSensorThreshold.controller_id == controller_id,
                        BmcSensorThreshold.controller_id.is_(None)),
                    BmcSensorThreshold.enabled.is_(True))
            .all())


def _resolve_sensor_threshold(rows, name, kind):
    """Pick the most specific threshold override for a sensor.

    Match priority: controller + name + kind > controller + kind >
    controller + name > controller > global + name + kind > global + kind >
    global + name > global.
    """
    target_name = (name or '').strip().lower()
    target_kind = (kind or '').strip().lower()
    best = None
    best_score = -1
    for row in rows:
        score = 0
        if row.controller_id is not None:
            score += 100
        if row.kind:
            if (row.kind or '').strip().lower() != target_kind:
                continue
            score += 10
        if row.name:
            if (row.name or '').strip().lower() != target_name:
                continue
            score += 5
        if score > best_score:
            best = row
            best_score = score
    return best


def _apply_sensor_threshold(sensor, threshold):
    """Overlay matching override values onto a Redfish sensor dict."""
    if threshold is None:
        return
    for field in ('lower_warning', 'upper_warning',
                  'lower_critical', 'upper_critical'):
        value = getattr(threshold, field, None)
        if value is not None:
            sensor[field] = value


def _sensor_breach(s):
    """Return the concrete threshold breach side for a sensor reading."""
    reading = s.get('reading')
    if reading is None:
        return 'unknown'
    try:
        value = float(reading)
    except (TypeError, ValueError):
        return 'unknown'

    lower_critical = s.get('lower_critical')
    upper_critical = s.get('upper_critical')
    lower_warning = s.get('lower_warning')
    upper_warning = s.get('upper_warning')

    def below(value, bound):
        if bound is None:
            return False
        try:
            return value <= float(bound)
        except (TypeError, ValueError):
            return False

    def above(value, bound):
        if bound is None:
            return False
        try:
            return value >= float(bound)
        except (TypeError, ValueError):
            return False

    if below(value, lower_critical):
        return 'critical_low'
    if above(value, upper_critical):
        return 'critical_high'
    if below(value, lower_warning):
        return 'warning_low'
    if above(value, upper_warning):
        return 'warning_high'
    return 'ok'


def _sensor_threshold_source(s, threshold):
    """Return the threshold source used for a persisted sensor reading."""
    if threshold is not None:
        return 'override'
    for field in ('lower_warning', 'upper_warning', 'lower_critical', 'upper_critical'):
        if s.get(field) is not None:
            return 'vendor'
    return 'none'


def _normalize_sensor_status(s):
    """Normalize BMC/Redfish sensor status and apply threshold fallback.

    Vendor status takes priority. If vendor does not report a clean ok/warning/
    critical state, the numeric reading is compared against warning/critical
    thresholds so alerting can still work for common temperature/fan/voltage
    sensors.
    """
    raw = (s.get('status') or '').strip().lower()
    if raw in ('warning', 'caution', 'noncritical', 'non-critical'):
        return 'warning'
    if raw in ('critical', 'failed', 'fatal', 'error'):
        return 'critical'
    if raw in ('ok', 'good', 'normal', 'informational', 'info'):
        return 'ok'

    breach = _sensor_breach(s)
    if breach in ('critical_low', 'critical_high'):
        return 'critical'
    if breach in ('warning_low', 'warning_high'):
        return 'warning'
    if breach == 'unknown':
        return 'ok' if not raw else raw
    return 'ok'

def _sensor_alert_title(dev, sensor):
    return 'BMC sensor abnormal: %s %s' % (dev.name if dev else 'BMC', sensor.name)


def _sensor_metric_type(sensor):
    return 'bmc_' + (sensor.kind or 'sensor')


def _sensor_state_key(sensor):
    """Return the durable key used for debounce state."""
    return (sensor.name or '').strip(), (sensor.kind or 'sensor').strip()


def _get_sensor_alert_state(session, ctrl, sensor):
    """Return the existing debounce row or create a fresh one."""
    name, kind = _sensor_state_key(sensor)
    state = (session.query(BmcSensorAlertState)
             .filter(BmcSensorAlertState.controller_id == ctrl.id,
                     BmcSensorAlertState.sensor_name == name,
                     BmcSensorAlertState.sensor_kind == kind)
             .first())
    if state is None:
        state = BmcSensorAlertState(
            controller_id=ctrl.id,
            sensor_name=name,
            sensor_kind=kind,
            normalized_status='ok',
            consecutive_strikes=0,
            updated_at=_now(),
        )
        session.add(state)
        session.flush()
    return state


def _evaluate_sensor_alert(session, dev, sensor, ctrl):
    """Raise/resolve BMC sensor alerts using durable consecutive-anomaly debounce.

    Unlike a pure history query, this keeps an explicit row per
    (controller, sensor name, kind). That makes the debounce state visible and
    prevents alert creation on a single transient warning/critical reading.
    Once the sensor returns to ok, the active alert is resolved automatically.
    """
    if dev is None:
        return
    cfg = _sensor_config()
    title = _sensor_alert_title(dev, sensor)
    metric_type = _sensor_metric_type(sensor)
    state = _get_sensor_alert_state(session, ctrl, sensor)
    previous_status = state.normalized_status
    state.normalized_status = sensor.status
    state.updated_at = _now()

    if sensor.status in ('warning', 'critical'):
        if previous_status == sensor.status:
            state.consecutive_strikes = (state.consecutive_strikes or 0) + 1
        else:
            state.consecutive_strikes = 1
        state.last_abnormal_at = _now()

        if state.consecutive_strikes >= cfg['strikes']:
            _raise_sensor_alert(session, dev, sensor, title, metric_type, state)
        else:
            logger.info(
                'OOB sensor pre-alert %s status=%s strikes=%s/%s',
                title, sensor.status, state.consecutive_strikes, cfg['strikes'],
            )
        return

    # Only a clean ok reading closes the alert. Unknown status is deliberately
    # non-resolving because it usually means the BMC stopped providing health.
    state.consecutive_strikes = 0
    if sensor.status == 'ok':
        state.last_ok_at = _now()
        _resolve_sensor_alert(session, dev, sensor, title, metric_type, state, ctrl)
    else:
        state.last_ok_at = None


def _raise_sensor_alert(session, dev, sensor, title, metric_type, state=None):
    severity = 'critical' if sensor.status == 'critical' else 'warning'
    message = '%s %s = %s%s (status=%s)' % (
        sensor.kind, sensor.name, sensor.reading, sensor.unit, sensor.status)
    existing = (session.query(AlertEvent)
                .filter(AlertEvent.device_id == dev.id,
                        AlertEvent.title == title,
                        AlertEvent.metric_type == metric_type,
                        AlertEvent.status == 'active')
                .order_by(AlertEvent.id.desc()).first())
    if existing:
        existing.message = message
        existing.severity = severity
        existing.metric_value = sensor.reading
        existing.last_occurred = _now()
        existing.occurrence_count = (existing.occurrence_count or 1) + 1
        if state is not None:
            state.alert_id = existing.id
        return
    ev = AlertEvent(
        device_id=dev.id,
        title=title,
        message=message,
        severity=severity,
        metric_type=metric_type,
        metric_value=sensor.reading,
    )
    session.add(ev)
    session.flush()
    ev.created_at = ev.first_occurred = ev.last_occurred = _now()
    if state is not None:
        state.alert_id = ev.id
    logger.info('OOB sensor alert: %s', title)


def _resolve_sensor_alert(session, dev, sensor, title, metric_type, state=None, ctrl=None):
    rows = (session.query(AlertEvent)
            .filter(AlertEvent.device_id == dev.id,
                    AlertEvent.title == title,
                    AlertEvent.metric_type == metric_type,
                    AlertEvent.status == 'active')
            .all())
    if not rows:
        if state is not None:
            state.alert_id = None
        return
    for ev in rows:
        ev.status = 'resolved'
        ev.resolved_at = _now()
        ev.resolved_by = 'oob_sensor_poll'
        ev.resolved_note = 'sensor recovered: %s=%s%s' % (
            sensor.name, sensor.reading, sensor.unit or '')
    if state is not None:
        state.alert_id = None
    if ctrl is not None:
        _send_sensor_recovery_notification(session, dev, sensor, ctrl)
    logger.info('OOB sensor alert resolved: %s', title)


def _send_sensor_recovery_notification(session, dev, sensor, ctrl):
    """Notify configured channels when a BMC sensor alert auto-recovers."""
    try:
        from flask import current_app
        if not current_app.config.get('OOB_SENSOR_NOTIFY_RECOVERY', True):
            return
    except RuntimeError:
        pass

    from models.models import NotificationConfig
    from services.notification_service import send_notification

    try:
        configs = (session.query(NotificationConfig)
                   .filter(NotificationConfig.enabled.is_(True)).all())
    except Exception as exc:
        logger.warning('OOB sensor recovery notification query failed: %s', exc)
        return
    if not configs:
        return

    values = {
        'device': dev.name if dev else (ctrl.name or ctrl.bmc_ip or '?'),
        'hostname': ctrl.bmc_ip or '',
        'ip': ctrl.bmc_ip or '',
        'sensor_name': sensor.name or '',
        'sensor_kind': sensor.kind or '',
        'reading': sensor.reading,
        'unit': sensor.unit or '',
        'status': sensor.status or 'ok',
    }
    default_title = 'BMC sensor recovered: {device} {sensor_name}'
    default_message = (
        'Device {device} ({ip}) sensor {sensor_name} ({sensor_kind}) '
        'recovered: {reading}{unit}'
    )
    for nc in configs:
        trigger = (nc.trigger_on or 'all').strip().lower()
        if trigger not in ('all', 'recovery', 'resolved'):
            continue
        title = (nc.title_template or default_title)
        content = (nc.message_template or default_message)
        for k, v in values.items():
            title = title.replace('{%s}' % k, str(v))
            content = content.replace('{%s}' % k, str(v))
        try:
            ok, msg = send_notification(nc, title=title, content=content)
            logger.info('OOB sensor recovery notify [%s] -> %s (%s)',
                        nc.name, ok, msg)
        except Exception as exc:
            logger.exception('OOB sensor recovery notify failed for %s: %s',
                             nc.name, exc)


_DEFAULT_SEL_TITLE = '【iDRAC 带外 SEL】{device} {severity}'
_DEFAULT_SEL_MESSAGE = (
    '设备 {device}（{ip}）通过 iDRAC 带外上报 SEL 事件\n'
    '时间：{log_time}\n级别：{severity}\n类型：{entry_type}\n'
    '事件ID：{event_id}\n消息：{description}'
)

_SEL_PLACEHOLDERS = {
    'device', 'hostname', 'ip', 'severity', 'message_id',
    'sensor_type', 'event_id', 'log_time', 'entry_type',
    'description', 'title', 'alert_id',
}


def _render_sel_template(text, ctrl, dev, e, ev):
    """Replace {placeholder} tokens in a SEL notification template."""
    if not text:
        return text
    values = {
        'device': dev.name if dev is not None else (ctrl.name or ctrl.bmc_ip or '?'),
        'hostname': getattr(ctrl, 'hostname', None) or ctrl.bmc_ip or '',
        'ip': ctrl.bmc_ip or '',
        'severity': ev.severity or (e.get('severity') or 'unknown'),
        'message_id': e.get('message_id') or '',
        'sensor_type': e.get('sensor_type') or '',
        'event_id': e.get('event_id') or '',
        'entry_type': e.get('entry_type') or '',
        'log_time': str(e.get('created') or ''),
        'description': e.get('message') or '',
        'title': ev.title or '',
        'alert_id': str(ev.id or ''),
    }
    out = text
    for k in _SEL_PLACEHOLDERS:
        out = out.replace('{%s}' % k, str(values.get(k, '')))
    return out


def _send_sel_notification(session, ev, ctrl, dev, e):
    """Dispatch a SEL alert to enabled NotificationConfig channels.

    Respects existing semantics: a NotificationConfig whose trigger_on is
    'all' or matches the alert severity receives the alert. Title/content
    templates may reference {device} {hostname} {ip} {severity}
    {message_id} {sensor_type} {event_id} {log_time} {entry_type}
    {description} {title} {alert_id}.
    """
    from models.models import NotificationConfig
    from services.notification_service import send_notification

    try:
        configs = (session.query(NotificationConfig)
                   .filter(NotificationConfig.enabled.is_(True)).all())
    except Exception as exc:
        logger.warning('OOB SEL notification query failed: %s', exc)
        return
    if not configs:
        return

    severity = (ev.severity or 'warning').lower()
    for nc in configs:
        trigger = (nc.trigger_on or 'all').strip().lower()
        if trigger not in ('all', severity):
            continue
        title = _render_sel_template(
            nc.title_template or _DEFAULT_SEL_TITLE, ctrl, dev, e, ev)
        content = _render_sel_template(
            nc.message_template or _DEFAULT_SEL_MESSAGE, ctrl, dev, e, ev)
        try:
            ok, msg = send_notification(nc, title=title, content=content)
            logger.info('OOB SEL notify [%s] -> %s (%s)', nc.name, ok, msg)
        except Exception as exc:
            logger.exception('OOB SEL notify failed for %s: %s', nc.name, exc)


def _parse_log_time(value):
    """Robustly parse BMC log timestamps (ISO8601 with/without timezone)."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f%z',
                '%Y-%m-%d %H:%M:%S'):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            continue
    return None


def _poll_event_logs(session, ctrl, mgr, dev):
    """Persist new BMC event logs and raise alerts for critical/warning items."""
    try:
        entries = mgr.get_logs(log_type='sel', max_entries=200)
    except OobError as e:
        logger.warning('OOB SEL read failed for %s: %s', ctrl.bmc_ip, e)
        return

    if not entries:
        return

    # existing (message_id, log_time) for this controller to avoid duplicates
    existing = set()
    for row in session.query(BmcEventLog.message_id, BmcEventLog.log_time).filter_by(
            controller_id=ctrl.id).all():
        if row.message_id:
            existing.add((row.message_id, row.log_time))

    for e in entries:
        log_ts = _parse_log_time(e.get('created'))
        key = (e.get('message_id'), log_ts)
        if key in existing:
            continue
        existing.add(key)
        row = BmcEventLog(
            controller_id=ctrl.id,
            entry_type=e.get('entry_type'),
            severity=e.get('severity'),
            message=e.get('message'),
            message_id=e.get('message_id'),
            sensor_type=e.get('sensor_type'),
            event_id=e.get('event_id'),
            log_time=log_ts,
            recorded_at=_now(),
        )
        session.add(row)
        severity = (e.get('severity') or '').lower()
        if severity in ('critical', 'warning', 'emergency', 'alert', 'error') and dev is not None:
            _raise_log_alert(session, dev, e, ctrl)
            row.alerted = True


def _raise_log_alert(session, dev, e, ctrl):
    """Raise a rule-driven AlertEvent for a critical SEL entry.

    Integrates with the existing event rule engine:
      * rule_id is taken from an enabled AlertRule(metric_type='bmc_sel') if any;
      * the event-correlation engine (process_alert_correlation) is applied so
        user-configured suppress/group/raise rules work on SEL alerts too;
      * a fallback dedup merges repeats when no correlation rule matched.
    """
    severity = ('critical' if (e.get('severity') or '').lower()
                in ('critical', 'emergency') else 'warning')
    title = 'BMC SEL %s: %s' % ((e.get('severity') or 'event'),
                                (e.get('message') or 'unknown'))[:200]

    rule = (session.query(AlertRule)
            .filter(AlertRule.metric_type == 'bmc_sel',
                    AlertRule.enabled.is_(True))
            .first())

    ev = AlertEvent(
        device_id=dev.id,
        rule_id=rule.id if rule else None,
        title=title,
        message=(e.get('message') or '')[:500],
        severity=severity,
        metric_type='bmc_sel',
        metric_value=None,
    )
    session.add(ev)
    session.flush()
    ev.created_at = ev.first_occurred = ev.last_occurred = _now()

    # 1) event-correlation rule engine (suppress / group / severity / ticket)
    action, _into = process_alert_correlation(session, ev)
    if action in ('suppress', 'group') and ev.status == 'suppressed':
        logger.info('OOB SEL alert merged into existing: %s', title)
        return

    # 2) fallback dedup: no rule matched, merge repeats within 24h
    since = _now() - timedelta(hours=24)
    dup = (session.query(AlertEvent)
           .filter(AlertEvent.device_id == dev.id,
                   AlertEvent.status == 'active',
                   AlertEvent.metric_type == 'bmc_sel',
                   AlertEvent.title == title,
                   AlertEvent.last_occurred >= since,
                   AlertEvent.id != ev.id)
           .order_by(AlertEvent.last_occurred.desc()).first())
    if dup:
        dup.occurrence_count = (dup.occurrence_count or 1) + 1
        dup.last_occurred = _now()
        ev.status = 'suppressed'
        ev.suppressed = True
        logger.info('OOB SEL alert fallback-merged (%d total): %s',
                    dup.occurrence_count, title)
    else:
        logger.info('OOB SEL alert: %s', title)
        # fresh alert -> dispatch configured notifications (通知联动)
        _send_sel_notification(session, ev, ctrl, dev, e)


def ensure_default_sel_rules(session):
    """Idempotently create a default BMC SEL correlation rule (dedup/group)."""
    from models.maintenance_models import EventCorrelationRule
    exists = (session.query(EventCorrelationRule)
              .filter(EventCorrelationRule.name == 'BMC SEL 默认关联')
              .first())
    if exists:
        return exists
    rule = EventCorrelationRule(
        name='BMC SEL 默认关联',
        description='BMC SEL Critical/Warning 事件按设备去重归并（24h 窗口）',
        enabled=True,
        priority_order=50,
        match_scope='title',
        match_operator='contains',
        match_value='BMC SEL',
        action='group',
        group_by='device_id',
        suppression_window_min=1440,
        auto_ticket=False,
    )
    session.add(rule)
    logger.info('Created default BMC SEL correlation rule')
    return rule


def poll_firmware_jobs(app=None):
    """Poll submitted/running firmware upgrade Tasks and write back status.

    Called by the scheduler (with app) or manually.
    """
    if app is not None:
        with app.app_context():
            _poll_firmware_jobs_impl()
    else:
        _poll_firmware_jobs_impl()


def _poll_firmware_jobs_impl():
    try:
        from flask import current_app
        if not current_app.config.get('OOB_ENABLED', True):
            return
    except RuntimeError:
        pass
    session = get_bg_session()
    try:
        jobs = (session.query(BmcFirmwareJob)
                .filter(BmcFirmwareJob.status.in_(['submitted', 'running']))
                .all())
        for job in jobs:
            ctrl = job.controller
            if job.task_ref is None or ctrl is None or not ctrl.credential:
                # 无 Task URI / 控制器 / 凭据 → 无法自动跟踪，显式标注供人工核对
                job.status = 'running'
                if not job.error:
                    job.error = '无 Task URI 可跟踪，请人工核对升级结果'
                continue
            mgr = OobManager(ctrl, ctrl.credential)
            try:
                st = mgr.get_task_status(job.task_ref)
            except OobError as e:
                # 网络抖动/任务尚未就绪：保持原状态，下轮再试
                logger.warning('firmware job %s poll failed: %s', job.id, e)
                continue
            if st.get('failed'):
                job.status = 'failed'
                job.error = st.get('message') or ('task state=%s' % st.get('state'))
                job.finished_at = _now()
            elif st.get('completed'):
                job.status = 'success'
                job.error = None
                job.finished_at = _now()
            else:
                job.status = 'running'
        session.commit()
    finally:
        session.close()
