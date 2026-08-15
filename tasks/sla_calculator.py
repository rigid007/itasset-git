"""
tasks/sla_calculator.py - SLA在线率计算任务
定期从DeviceMonitorLog计算设备在线率，写入SlaUptime表
"""
from datetime import datetime, timedelta
from extensions import db
from models.models import Device
from models.monitoring import SlaUptime


# 设备"状态类"监控日志的 monitor_type 集合。
# SLA 仅据此聚合设备在线/离线（排除 link_monitor 等链路类日志）。
# 事件驱动监控写入的 'trap'/'syslog'/'event' 也包含在内，
# 使 SNMP Trap / syslog 触发的秒级离线能计入可用率。
DEVICE_STATUS_MONITOR_TYPES = {
    'device_ping', 'auto_ping', 'snmp', 'ping', 'trap', 'syslog', 'event',
}


def calculate_sla(app):
    """计算所有设备的SLA在线率（周期: monthly/quarterly/yearly）"""
    with app.app_context():
        from models import DeviceMonitorLog
        now = datetime.utcnow()

        periods = _get_periods(now)
        devices = Device.query.all()

        for device in devices:
            for period_name, start, end in periods:
                _calc_device_sla(device.id, period_name, start, end)

        db.session.commit()


def _calc_device_sla(device_id, period, period_start, period_end):
    """计算单个设备在指定周期内的SLA

    优化：基于 DeviceMonitorLog 状态转换时间差精确计算宕机时长，
    而非旧的"离线条数×5分钟"粗略估算。
    统计所有"设备状态类"日志（monitor_type in DEVICE_STATUS_MONITOR_TYPES），
    排除 link_monitor 等链路类日志，同时涵盖轮询与事件驱动（trap/syslog/event）来源。
    """
    from models import DeviceMonitorLog

    # 周期内的总分钟数
    total_seconds = (period_end - period_start).total_seconds()
    total_minutes = max(int(total_seconds / 60), 1)

    # 查询周期内所有设备状态转换日志（按时间排序）
    logs = DeviceMonitorLog.query.filter(
        DeviceMonitorLog.device_id == device_id,
        DeviceMonitorLog.monitor_type.in_(DEVICE_STATUS_MONITOR_TYPES),
        DeviceMonitorLog.created_at.between(period_start, period_end),
    ).order_by(DeviceMonitorLog.created_at).all()

    # 检查周期开始前设备是否已处于离线状态
    prior_log = DeviceMonitorLog.query.filter(
        DeviceMonitorLog.device_id == device_id,
        DeviceMonitorLog.monitor_type.in_(DEVICE_STATUS_MONITOR_TYPES),
        DeviceMonitorLog.created_at < period_start,
    ).order_by(DeviceMonitorLog.created_at.desc()).first()

    downtime_minutes = 0.0
    offline_start = None

    # 如果周期开始前最后一次状态是离线，从周期起始开始计宕机
    if prior_log and not prior_log.is_online:
        offline_start = period_start

    # 遍历状态转换日志，配对 offline→online 计算实际宕机时长
    for log in logs:
        if not log.is_online and offline_start is None:
            # 进入离线状态
            offline_start = log.created_at
        elif log.is_online and offline_start is not None:
            # 恢复在线，计算宕机时长
            delta = (log.created_at - offline_start).total_seconds() / 60
            downtime_minutes += max(delta, 0)
            offline_start = None

    # 如果周期结束时仍处于离线，计到周期结束
    if offline_start is not None:
        delta = (period_end - offline_start).total_seconds() / 60
        downtime_minutes += max(delta, 0)

    downtime_minutes = min(downtime_minutes, total_minutes)
    uptime_pct = round((1 - downtime_minutes / total_minutes) * 100, 3)

    # upsert
    existing = SlaUptime.query.filter_by(
        device_id=device_id, period=period, period_start=period_start
    ).first()
    if existing:
        existing.uptime_percentage = uptime_pct
        existing.total_minutes = total_minutes
        existing.downtime_minutes = downtime_minutes
        existing.calculated_at = datetime.utcnow()
    else:
        sla = SlaUptime(
            device_id=device_id,
            period=period,
            uptime_percentage=uptime_pct,
            total_minutes=total_minutes,
            downtime_minutes=downtime_minutes,
            period_start=period_start,
            period_end=period_end,
        )
        db.session.add(sla)


def _get_periods(now):
    """获取当前需要计算的周期范围"""
    periods = []

    # 月度：当前月1号 ~ 当前时间
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    periods.append(('monthly', month_start, now))

    # 季度：当前季度初 ~ 当前时间
    quarter_month = ((now.month - 1) // 3) * 3 + 1
    quarter_start = now.replace(month=quarter_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    periods.append(('quarterly', quarter_start, now))

    # 年度：当年1月1日 ~ 当前时间
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    periods.append(('yearly', year_start, now))

    return periods
