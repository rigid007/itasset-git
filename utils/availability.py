"""真实可用率采集 —— 对接监控/设备在线状态(DeviceMonitorLog)

替代 CSI 仪表盘中基于工单解决时长的代理算法。
可用率 = 1 - 总停机时长 / 统计窗长。
  - 设备级：由 DeviceMonitorLog 的 is_online 跃迁推算停机区间。
  - 服务级：服务目录映射设备(ServiceCatalogDevice)做「任一设备宕机即服务不可用」并集。
"""
from datetime import datetime, timedelta


def _device_down_intervals(device_id, start, end):
    """返回该设备在 [start,end] 内的停机区间列表 [(down_start, down_end), ...]。"""
    from models.models import DeviceMonitorLog
    logs = DeviceMonitorLog.query.filter(
        DeviceMonitorLog.device_id == device_id,
        DeviceMonitorLog.created_at >= start,
        DeviceMonitorLog.created_at <= end,
    ).order_by(DeviceMonitorLog.created_at.asc()).all()

    intervals = []
    down_start = None
    for log in logs:
        if not log.is_online:
            if down_start is None:
                down_start = log.created_at
        else:
            if down_start is not None:
                intervals.append((down_start, log.created_at))
                down_start = None
    if down_start is not None:
        intervals.append((down_start, end))
    return intervals


def _merge_intervals(intervals):
    if not intervals:
        return []
    sorted_i = sorted(intervals, key=lambda x: x[0])
    merged = [list(sorted_i[0])]
    for s, e in sorted_i[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def _interval_minutes(intervals):
    return sum((e - s).total_seconds() / 60.0 for s, e in intervals)


def _has_any_log(device_id, start, end):
    from models.models import DeviceMonitorLog
    return DeviceMonitorLog.query.filter(
        DeviceMonitorLog.device_id == device_id,
        DeviceMonitorLog.created_at >= start,
        DeviceMonitorLog.created_at <= end,
    ).count() > 0


def compute_device_availability(device_id, start, end):
    """计算单设备真实可用率。无日志时视为 100%(无法证明宕机)。"""
    total_minutes = max((end - start).total_seconds() / 60.0, 1)
    intervals = _device_down_intervals(device_id, start, end)
    down_minutes = _interval_minutes(intervals)
    availability = round(100.0 * (1 - down_minutes / total_minutes), 2)
    availability = max(0.0, min(availability, 100.0))
    return {
        'device_id': device_id,
        'total_minutes': round(total_minutes, 1),
        'down_minutes': round(down_minutes, 1),
        'availability_pct': availability,
        'has_data': bool(intervals) or _has_any_log(device_id, start, end),
    }


def compute_service_availability(device_ids, start, end):
    """多设备并集：任一设备宕机即服务不可用。"""
    if not device_ids:
        return {'total_minutes': 0, 'down_minutes': 0, 'availability_pct': None, 'has_data': False}
    all_intervals = []
    for did in device_ids:
        all_intervals.extend(_device_down_intervals(did, start, end))
    merged = _merge_intervals(all_intervals)
    total_minutes = max((end - start).total_seconds() / 60.0, 1)
    down_minutes = _interval_minutes(merged)
    availability = round(100.0 * (1 - down_minutes / total_minutes), 2)
    availability = max(0.0, min(availability, 100.0))
    return {
        'total_minutes': round(total_minutes, 1),
        'down_minutes': round(down_minutes, 1),
        'availability_pct': availability,
        'has_data': bool(all_intervals),
    }


def collect_availability(session, start=None, end=None, days=30, devices=None):
    """采集并写入 AvailabilityRecord。返回统计 dict。

    - 每个在窗口内有监控日志的设备写一条 scope='device'
    - 每个映射了设备的服务目录写一条 scope='service'(并集)
    """
    from models.models import DeviceMonitorLog, AlertEvent
    from models.maintenance_models import (
        AvailabilityRecord, ServiceCatalog,
    )

    if end is None:
        end = datetime.utcnow()
    if start is None:
        start = end - timedelta(days=days)

    subq = session.query(DeviceMonitorLog.device_id).filter(
        DeviceMonitorLog.created_at >= start,
        DeviceMonitorLog.created_at <= end,
    ).distinct()
    device_ids = [r[0] for r in subq.all()]
    if devices is not None:
        device_ids = [d for d in device_ids if d in set(devices)]

    written = 0
    device_rows = []
    for did in device_ids:
        rec = compute_device_availability(did, start, end)
        inc = AlertEvent.query.filter(
            AlertEvent.device_id == did,
            AlertEvent.first_occurred >= start,
            AlertEvent.first_occurred <= end,
        ).count()
        ar = AvailabilityRecord(
            scope='device', device_id=did,
            period_start=start, period_end=end,
            total_minutes=rec['total_minutes'], down_minutes=rec['down_minutes'],
            availability_pct=rec['availability_pct'], incident_count=inc,
            source='device_monitor_log',
        )
        session.add(ar)
        written += 1
        device_rows.append({'device_id': did, 'availability_pct': rec['availability_pct']})

    services = ServiceCatalog.query.filter_by(enabled=True).all()
    service_rows = []
    for svc in services:
        devs = [d.id for d in svc.mapped_devices.all()]
        if not devs:
            continue
        devs_in_window = [d for d in devs if d in device_ids]
        if not devs_in_window:
            continue
        rec = compute_service_availability(devs_in_window, start, end)
        ar = AvailabilityRecord(
            scope='service', service_catalog_id=svc.id,
            period_start=start, period_end=end,
            total_minutes=rec['total_minutes'], down_minutes=rec['down_minutes'],
            availability_pct=rec['availability_pct'], source='device_monitor_log',
        )
        session.add(ar)
        written += 1
        service_rows.append({'service_id': svc.id, 'availability_pct': rec['availability_pct']})

    return {'written': written, 'device_rows': device_rows, 'service_rows': service_rows}


def get_real_availability(service_id, start, end):
    """读取已采集的服务级真实可用率(最新一条)。无则返回 None。"""
    from models.maintenance_models import AvailabilityRecord
    rec = AvailabilityRecord.query.filter_by(
        scope='service', service_catalog_id=service_id,
    ).filter(
        AvailabilityRecord.period_start >= start,
        AvailabilityRecord.period_end <= end,
    ).order_by(AvailabilityRecord.created_at.desc()).first()
    if rec:
        return rec.availability_pct
    return None
