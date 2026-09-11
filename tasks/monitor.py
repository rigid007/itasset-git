# tasks/monitor.py
from flask import Flask
from extensions import db
from models.models import (
    Device, DeviceMonitorConfig, MonitorData, AlertRule, AlertEvent, NotificationConfig,
    DeviceMonitorLog, Interface,
)
from utils.utils import ping_device, get_device_snmp_data, snmp_get_with_timeout
from datetime import datetime
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Parallel collection threads. Network I/O is the bottleneck; this value can be
# tuned for the production DB pool (default pool_size=20 + overflow=30).
METRIC_COLLECT_WORKERS = 30

# In-process last-collection timestamps for per-method interval control.
# Keyed by DeviceMonitorConfig.id. Resets on process restart, which only
# causes one extra collection round after a restart (harmless).
_last_ping_at = {}
_last_snmp_at = {}

# In-process consecutive-collection-failure tracker. Each value is the number
# of consecutive unified poll rounds where no enabled method succeeded.
_consecutive_failures = {}

# Default threshold for creating a "collection unavailable" alert. This is
# deliberately conservative: the unified poll runs every 60s, so 3 rounds means
# about 3 minutes of repeated failure before notifying.
COLLECTION_FAILURE_ALERT_AFTER = 3


def _collection_failure_title(device_name):
    return f"采集失败: {device_name}"


def _device_alerts_by_collection_failure(device_id):
    return AlertEvent.query.filter_by(
        device_id=device_id,
        rule_id=None,
    ).filter(
        AlertEvent.title.like("采集失败:%")
    ).all()




def _build_unified_snapshots(app):
    """Build one snapshot per monitorable device.

    Devices with an explicitly disabled DeviceMonitorConfig are skipped. Devices
    without a config keep the legacy default behaviour: ping if IP exists, SNMP
    if community is configured. The resulting snapshot is detached-safe and can
    be used by worker threads without holding a DB session during network I/O.
    """
    with app.app_context():
        all_configs = {c.device_id: c for c in DeviceMonitorConfig.query.all()}
        devices = Device.query.filter_by(is_decommissioned=False).all()
        snapshots = []
        for dev in devices:
            cfg = all_configs.get(dev.id)
            if cfg is not None and not cfg.enabled:
                continue
            ip = dev.management_ip or dev.ip_address
            if cfg:
                enable_ping = bool(getattr(cfg, 'enable_ping', True))
                enable_snmp = bool(getattr(cfg, 'enable_snmp', False))
                ping_interval = max(int(getattr(cfg, 'ping_interval', 60) or 60), 5)
                snmp_interval = max(int(getattr(cfg, 'snmp_interval', 300) or 300), 5)
                ping_timeout = float(getattr(cfg, 'ping_timeout', 2.0) or 2.0)
                snmp_timeout = float(getattr(cfg, 'snmp_timeout', 3.0) or 3.0)
                snmp_community = getattr(cfg, 'snmp_community', None) or getattr(dev, 'snmp_community', 'public')
                snmp_version = getattr(cfg, 'snmp_version', None) or getattr(dev, 'snmp_version', '2c')
            else:
                enable_ping = True
                enable_snmp = bool(getattr(dev, 'snmp_community', None))
                ping_interval = 60
                snmp_interval = 300
                ping_timeout = 2.0
                snmp_timeout = 3.0
                snmp_community = getattr(dev, 'snmp_community', 'public')
                snmp_version = getattr(dev, 'snmp_version', '2c')

            snapshots.append({
                'device_id': dev.id,
                'name': dev.name,
                'ip': ip,
                'no_ip': not bool(ip),
                'old_status': dev.status or 'unknown',
                'vendor': getattr(dev, 'vendor', ''),
                'device_type': getattr(dev, 'device_type', ''),
                'enable_ping': enable_ping,
                'enable_snmp': enable_snmp,
                'ping_interval': ping_interval,
                'snmp_interval': snmp_interval,
                'ping_timeout': ping_timeout,
                'snmp_timeout': snmp_timeout,
                'snmp_community': snmp_community,
                'snmp_version': snmp_version,
            })
    return snapshots


def _unified_collect_device(snap):
    """Collect one device without holding a DB connection.

    Returns (row, result). ``row`` is inserted into MonitorData; ``result`` is
    used by the main thread to update Device.status and status transition logs.
    """
    row = None
    result = {
        'device_id': snap['device_id'],
        'checked': True,
        'no_ip': snap['no_ip'],
        'is_online': False,
        'snmp_ok': False,
        'ping_ok': False,
        'ping_time': None,
        'collection_failed': False,
    }
    if snap['no_ip']:
        result['collection_failed'] = True
        return row, result

    now = time.time()
    device_id = snap['device_id']
    ping_due = snap['enable_ping'] and (now - _last_ping_at.get(device_id, 0.0) >= snap['ping_interval'])
    snmp_due = snap['enable_snmp'] and (now - _last_snmp_at.get(device_id, 0.0) >= snap['snmp_interval'])
    if not ping_due and not snmp_due:
        result['checked'] = False
        result['collection_failed'] = False
        return row, result

    ping_ok = False
    rtt = None
    snmp_data = {}
    snmp_reachable = False

    if ping_due:
        try:
            ping_ok, rtt = ping_device(snap['ip'], timeout=snap['ping_timeout'])
        except Exception as e:
            logger.debug('Ping %s failed: %s', snap['ip'], e)
        _last_ping_at[device_id] = now

    if snmp_due:
        try:
            from types import SimpleNamespace
            dev_view = SimpleNamespace(
                management_ip=snap['ip'],
                snmp_community=snap['snmp_community'],
                snmp_version=snap['snmp_version'],
                vendor=snap['vendor'],
                device_type=snap['device_type'],
            )
            snmp_data = get_device_snmp_data(dev_view, timeout=snap['snmp_timeout']) or {}
        except Exception as e:
            logger.debug('SNMP metrics collect %s failed: %s', snap['ip'], e)

        try:
            sys_name = snmp_get_with_timeout(
                snap['ip'],
                snap['snmp_community'],
                snap['snmp_version'],
                '1.3.6.1.2.1.1.5.0',
                timeout=snap['snmp_timeout'],
            )
            snmp_reachable = sys_name is not None
        except Exception as e:
            logger.debug('SNMP reachability check %s failed: %s', snap['ip'], e)

        _last_snmp_at[device_id] = now

    snmp_ok = snmp_reachable or any(v is not None for v in snmp_data.values())
    result['ping_ok'] = ping_ok
    result['snmp_ok'] = snmp_ok
    result['is_online'] = bool(ping_ok or snmp_ok)
    result['collection_failed'] = not result['is_online']
    result['ping_time'] = rtt if ping_ok else None

    row = {
        'device_id': device_id,
        'cpu_usage': snmp_data.get('cpu_usage'),
        'memory_usage': snmp_data.get('memory_usage'),
        'disk_usage': snmp_data.get('disk_usage'),
        'temperature': snmp_data.get('temperature'),
        'power_consumption': snmp_data.get('power_consumption'),
        'ping_time': rtt if ping_ok else None,
        'is_reachable': result['is_online'],
        'has_errors': False,
        'monitor_type': 'unified',
        'collected_at': datetime.utcnow(),
    }
    return row, result


def _resolve_collection_failure_alerts(device_id):
    """Close active collection-failure alerts for a device."""
    now = datetime.utcnow()
    alerts = _device_alerts_by_collection_failure(device_id)
    for alert in alerts:
        if alert.status in ('active', 'suppressed'):
            alert.status = 'resolved'
            alert.resolved_at = now
            alert.resolved_by = 'system'
    return bool(alerts)


def _upsert_collection_failure_alert(device):
    """Create or refresh an active collection-failure alert for a device."""
    now = datetime.utcnow()
    ip = device.management_ip or device.ip_address or 'N/A'
    title = _collection_failure_title(device.name)
    alert = AlertEvent.query.filter_by(
        device_id=device.id,
        rule_id=None,
        metric_type='collection_failure',
        status='active',
    ).first()

    message = (
        f"\u8bbe\u5907 {device.name} ({ip}) \u8fde\u7eed {_consecutive_failures.get(device.id, 0)} "
        f"\u6b21\u91c7\u96c6\u5931\u8d25\uff0c\u53ef\u80fd\u4e3a Ping/SNMP \u4e0d\u53ef\u8fbe\u6216\u65e0\u7ba1\u7406IP\u3002"
    )
    if alert:
        alert.last_occurred = now
        alert.occurrence_count = (alert.occurrence_count or 0) + 1
        alert.message = message
        alert.severity = 'critical'
    else:
        alert = AlertEvent(
            device_id=device.id,
            rule_id=None,
            title=title,
            message=message,
            severity='critical',
            metric_type='collection_failure',
            metric_value=None,
            status='active',
            first_occurred=now,
            last_occurred=now,
            occurrence_count=1,
            notified=False,
        )
        db.session.add(alert)
    return alert


def _update_collection_failure_state(device):
    """Track consecutive unified-collection failures and manage alert lifecycle."""
    failed = bool(_consecutive_failures.get(device.id, 0) >= COLLECTION_FAILURE_ALERT_AFTER)
    if failed:
        _upsert_collection_failure_alert(device)
    else:
        _resolve_collection_failure_alerts(device.id)


def _apply_device_status(app, result):
    """Update Device.status and write status transition logs/alerts."""
    with app.app_context():
        dev = Device.query.get(result['device_id'])
        if not dev:
            return
        if not result.get('checked', True):
            return
        dev.last_checked = datetime.utcnow()
        if result.get('ping_time') is not None:
            dev.ping_time = result['ping_time']

        if result.get('collection_failed'):
            _consecutive_failures[dev.id] = _consecutive_failures.get(dev.id, 0) + 1
        else:
            _consecutive_failures[dev.id] = 0
        _update_collection_failure_state(dev)

        no_ip = result.get('no_ip')
        if no_ip:
            new_status = 'offline'
            is_online = False
            snmp_ok = False
            ping_ok = False
            error_message = '无管理IP'
        else:
            is_online = result.get('is_online', False)
            snmp_ok = result.get('snmp_ok', False)
            ping_ok = result.get('ping_ok', False)
            new_status = 'online' if is_online else 'offline'
            if is_online:
                error_message = None
            elif not snmp_ok and not ping_ok:
                error_message = 'SNMP+Ping均失败'
            elif not snmp_ok:
                error_message = 'SNMP失败'
            else:
                error_message = 'Ping失败'

        status_changed = dev.status != new_status
        old_status = dev.status
        if status_changed:
            dev.status = new_status
            logger.info('Device %s status change: %s -> %s', dev.name, old_status, new_status)

            try:
                db.session.add(DeviceMonitorLog(
                    device_id=dev.id,
                    device_ip=(dev.management_ip or dev.ip_address or 'N/A'),
                    old_status=old_status,
                    new_status=new_status,
                    ping_time=dev.ping_time or 0,
                    is_online=is_online,
                    monitor_type='unified_poll',
                    error_message=error_message,
                ))
            except Exception as e:
                logger.error('Write DeviceMonitorLog failed for device #%s: %s', dev.id, e)

            if new_status == 'offline':
                try:
                    alert = AlertEvent(
                        device_id=dev.id,
                        rule_id=None,
                        title=f'设备离线: {dev.name}',
                        message=f'设备 {dev.name} ({dev.management_ip or dev.ip_address or "N/A"}) 状态变化: {old_status} -> offline',
                        severity='critical',
                        status='active',
                        first_occurred=datetime.utcnow(),
                        last_occurred=datetime.utcnow(),
                        occurrence_count=1,
                        notified=False,
                    )
                    db.session.add(alert)
                    db.session.flush()
                    try:
                        from utils.event_correlation import process_alert_correlation
                        process_alert_correlation(db.session, alert)
                    except Exception as ce:
                        logger.error('Event correlation failed for offline alert (ignored): %s', ce)
                except Exception as ae:
                    logger.error('Create offline alert failed for device #%s (ignored): %s', dev.id, ae)
            elif new_status == 'online':
                try:
                    dev_alerts = AlertEvent.query.filter_by(device_id=dev.id).filter(
                        AlertEvent.status.in_(['active', 'suppressed']),
                        AlertEvent.title.like('设备离线%')
                    ).all()
                    for a in dev_alerts:
                        a.status = 'resolved'
                        a.resolved_at = datetime.utcnow()
                        a.resolved_by = 'system'
                except Exception as re_:
                    logger.error('Resolve offline alerts failed for device #%s: %s', dev.id, re_)

        if not is_online:
            try:
                interfaces = Interface.query.filter_by(device_id=dev.id).all()
                changed_ifaces = 0
                for iface in interfaces:
                    if iface.oper_status != 'down':
                        iface.oper_status = 'down'
                        iface.updated_at = datetime.utcnow()
                        changed_ifaces += 1
                if changed_ifaces:
                    logger.info('Device %s offline, marked %s interfaces down', dev.name, changed_ifaces)
            except Exception as ie:
                logger.error('Mark interfaces down failed for device #%s: %s', dev.id, ie)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Commit device status failed for device #%s', dev.id)


def unified_device_poll(app: Flask):
    """Unified status + metrics poll.

    This replaces the old split where status detection pinged every device and
    metric collection pinged enabled configs again. One scheduling pass now:
      1. collects ping/SNMP data according to per-device intervals
      2. writes one MonitorData row only when at least one method actually ran
      3. updates Device.status and transition logs/alerts once per pass
    """
    snapshots = _build_unified_snapshots(app)
    logger.info('Unified device poll started for %s devices', len(snapshots))

    rows = []
    results = []
    start = time.time()
    with ThreadPoolExecutor(max_workers=METRIC_COLLECT_WORKERS) as executor:
        futures = {executor.submit(_unified_collect_device, snap): snap['device_id'] for snap in snapshots}
        for future in as_completed(futures):
            try:
                row, result = future.result() or (None, None)
                if result:
                    results.append(result)
                if row:
                    rows.append(row)
            except Exception as e:
                logger.error('Unified collect subtask failed: %s', e)

    if rows:
        with app.app_context():
            try:
                db.session.bulk_insert_mappings(MonitorData, rows)
                db.session.commit()
                logger.info('Bulk inserted %s MonitorData rows', len(rows))
            except Exception as e:
                db.session.rollback()
                logger.error('Bulk insert MonitorData failed: %s', e)

    for result in results:
        try:
            _apply_device_status(app, result)
        except Exception as e:
            logger.error('Apply device status failed for device #%s: %s', result.get('device_id'), e)

    elapsed = time.time() - start
    logger.info('Unified device poll finished: %s rows, %s status checks, took %.2fs', len(rows), len(results), elapsed)


def collect_device_metrics(app: Flask):
    """Backward-compatible wrapper for code that still imports the old name."""
    return unified_device_poll(app)


def _get_rule_devices(rule):
    """Return devices targeted by an AlertRule (apply_to_all / device_ids)."""
    q = Device.query.filter_by(is_decommissioned=False)
    if getattr(rule, 'apply_to_all', True):
        return q.all()

    ids = []
    raw = getattr(rule, 'device_ids', None)
    if raw:
        try:
            if isinstance(raw, str):
                raw = raw.strip()
                if raw.startswith('['):
                    ids = [int(x) for x in json.loads(raw)]
                else:
                    ids = [int(x.strip()) for x in raw.split(',') if x.strip()]
            elif isinstance(raw, list):
                ids = [int(x) for x in raw]
        except Exception:
            ids = []
    if ids:
        return q.filter(Device.id.in_(ids)).all()
    return q.all()


def _metric_value_from_monitor_data(record, metric_type):
    mapping = {
        'cpu': record.cpu_usage,
        'cpu_usage': record.cpu_usage,
        'memory': record.memory_usage,
        'memory_usage': record.memory_usage,
        'disk': record.disk_usage,
        'disk_usage': record.disk_usage,
        'ping': record.ping_time,
        'ping_time': record.ping_time,
        'temperature': record.temperature,
        'power': record.power_consumption,
        'power_consumption': record.power_consumption,
    }
    return mapping.get(metric_type)


def evaluate_alerts(app: Flask):
    """Evaluate enabled AlertRules against the latest MonitorData rows.

    This replaces the old implementation that referenced non-existent fields on
    the current AlertRule model (device_config_id / operator / metric_name).
    """
    with app.app_context():
        rules = AlertRule.query.filter_by(enabled=True).all()
        for rule in rules:
            try:
                for device in _get_rule_devices(rule):
                    latest = MonitorData.query.filter_by(device_id=device.id)\
                        .order_by(MonitorData.collected_at.desc()).first()
                    if not latest:
                        continue
                    value = _metric_value_from_monitor_data(latest, rule.metric_type)
                    if value is None:
                        continue
                    if _compare(value, rule.condition, rule.threshold):
                        _trigger_alert(rule, device, latest, value)
                    else:
                        _resolve_alert(rule, device)
            except Exception as e:
                logger.error('Evaluate alert rule #%s failed: %s', rule.id, e)


def _compare(value, operator, threshold):
    if value is None:
        return False
    if operator == '>':
        return value > threshold
    elif operator == '<':
        return value < threshold
    elif operator == '>=':
        return value >= threshold
    elif operator == '<=':
        return value <= threshold
    elif operator == '==':
        return value == threshold
    return False


def _trigger_alert(rule, device, latest, current_value):
    now = datetime.utcnow()
    ip = device.management_ip or device.ip_address or ''
    message = (f"{device.name} ({ip}) {rule.metric_type} current value {current_value} "
               f"triggered alert (threshold {rule.condition}{rule.threshold})")
    title = f"{device.name} {rule.metric_type} alert"

    alert = AlertEvent.query.filter_by(
        rule_id=rule.id,
        device_id=device.id,
        metric_type=rule.metric_type,
        status='active',
    ).first()
    should_notify = False
    if alert:
        alert.last_occurred = now
        alert.occurrence_count = (alert.occurrence_count or 0) + 1
        alert.metric_value = current_value
        alert.message = message
        alert.severity = rule.severity
        repeat_interval = int(getattr(rule, 'repeat_interval', 0) or 0)
        if repeat_interval > 0 and (not alert.notification_sent_at or
                                    (now - alert.notification_sent_at).total_seconds() >= repeat_interval):
            should_notify = True
    else:
        should_notify = True
        alert = AlertEvent(
            rule_id=rule.id,
            device_id=device.id,
            title=title,
            message=message,
            severity=rule.severity,
            metric_type=rule.metric_type,
            metric_value=current_value,
            status='active',
            first_occurred=now,
            last_occurred=now,
            occurrence_count=1,
        )
        db.session.add(alert)
    if should_notify:
        alert.notified = True
        alert.notification_sent_at = now
    db.session.commit()

    if should_notify:
        _send_notification(rule, message)


def _resolve_alert(rule, device):
    alerts = AlertEvent.query.filter_by(
        rule_id=rule.id,
        device_id=device.id,
        metric_type=rule.metric_type,
        status='active',
    ).all()
    if not alerts:
        return
    now = datetime.utcnow()
    for a in alerts:
        a.status = 'resolved'
        a.resolved_at = now
        a.resolved_by = 'system'
    db.session.commit()


def _send_notification(rule, message):
    """Send alert notifications through enabled NotificationConfigs."""
    from services.notification_service import send_notification

    if not (getattr(rule, 'notify_email', False) or
            getattr(rule, 'notify_webhook', False) or
            getattr(rule, 'notify_sms', False)):
        return

    configs = NotificationConfig.query.filter_by(enabled=True).all()
    if not configs:
        return

    title = f'[{rule.name}] - {rule.severity.upper()}'

    for nc in configs:
        try:
            send_notification(nc, title=title, content=message)
        except Exception as e:
            print(f"Send notification failed [{nc.name}]: {e}")

