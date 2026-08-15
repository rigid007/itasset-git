# routes.py (main_routes.py)
"""
主蓝图路由模块 - 仪表盘和主页相关路由
"""
from flask import Blueprint, render_template, current_app, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, and_, select
from extensions import db
from models.models import Location, Cabinet, Device, OperationLog, AlertEvent
from models.models import DeviceMonitorLog, DiscoveryTask, Interface
from models.device_group_models import DeviceGroup, device_group_members
from auth import log_operation
from datetime import datetime, timezone, timedelta
import pytz
# 创建主蓝图
main = Blueprint('main', __name__)


@main.route('/')
@main.route('/dashboard')
@login_required
def index():
    """仪表盘主页面"""
    try:
        # 获取当前日期（北京时间）
        beijing_tz = pytz.timezone('Asia/Shanghai')
        current_date = datetime.now(beijing_tz)
        
        # ==================== 1. 设备统计（单次查询） ====================
        # 使用 GROUP BY 一次性获取所有状态统计（排除已下架设备）
        status_stats = db.session.query(
            Device.status,
            func.count(Device.id).label('count')
        ).filter(Device.is_decommissioned == False).group_by(Device.status).all()
        
        # 转换为字典便于访问
        status_count = {status: count for status, count in status_stats}
        
        total_devices = sum(status_count.values())
        online_devices = status_count.get('online', 0)
        offline_devices = status_count.get('offline', 0)
        fault_devices = status_count.get('fault', 0)
        
        # 在线率
        online_rate = (online_devices / total_devices * 100) if total_devices > 0 else 0
        
        # 本月新增设备（使用 UTC 时间）
        first_day_of_month = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        new_devices_this_month = Device.query.filter(
            Device.created_at >= first_day_of_month,
            Device.is_decommissioned == False
        ).count()
        
        # ==================== 2. 位置统计（单次查询） ====================
        total_locations = Location.query.count()
        
        # 数据中心类型的位置统计（使用 SQL 级别的过滤）
        data_center_locations = Location.query.filter(
            Location.location_type.ilike('%data_center%') | 
            Location.location_type.ilike('%数据中心%')
        ).count()
        
        # ==================== 3. 机柜统计（优化 N+1 查询） ====================
        total_cabinets = Cabinet.query.count()
        
        # 修复：正确使用 LEFT JOIN，添加 Location 和 Cabinet 之间的关联条件
        # Cabinet 表有 location_id 外键关联到 Location 表
        cabinet_usage_query = db.session.query(
            Cabinet.id,
            Cabinet.name,
            Cabinet.height_u,
            Location.name.label('location_name'),
            func.count(Device.id).label('device_count')
        ).outerjoin(
            Location, Cabinet.location_id == Location.id  # 修复：添加正确的 JOIN 条件
        ).outerjoin(
            Device, and_(Cabinet.id == Device.cabinet_id, Device.is_decommissioned == False)
        ).group_by(
            Cabinet.id, Cabinet.name, Cabinet.height_u, Location.name
        ).all()
        
        # 计算机柜平均使用率和机柜状态列表
        total_usage = 0
        cabinet_count_with_usage = 0
        cabinet_status = []
        
        for cabinet_id, cabinet_name, height_u, location_name, device_count in cabinet_usage_query:
            used_slots = device_count
            if height_u and height_u > 0:
                usage_percent = (used_slots / height_u) * 100
                total_usage += usage_percent
                cabinet_count_with_usage += 1
            else:
                usage_percent = 0
            
            cabinet_status.append({
                'name': cabinet_name,
                'location': location_name or '未指定',
                'total_slots': height_u or 42,
                'used_slots': used_slots,
                'usage_percent': round(usage_percent, 1)
            })
        
        cabinet_avg_usage = total_usage / cabinet_count_with_usage if cabinet_count_with_usage > 0 else 0
        
        # 只取前5个机柜用于仪表盘显示
        cabinet_status_top5 = cabinet_status[:5]
        
        # ==================== 4. 设备类型分布（单次查询） ====================
        device_types_query = db.session.query(
            Device.device_type,
            func.count(Device.id).label('count')
        ).group_by(Device.device_type).all()
        
        # 设备类型中文映射
        type_mapping = {
            'router': '路由器',
            'switch': '交换机',
            'firewall': '防火墙',
            'server': '服务器',
            'pc': '计算机',
            'ap': '无线AP',
            'storage': '存储设备',
            'unknown': '其他设备'
        }
        
        device_type_distribution = {}
        for device_type, count in device_types_query:
            if device_type is None:
                display_name = "未指定"
            else:
                display_name = type_mapping.get(device_type, device_type)
            device_type_distribution[display_name] = count
        
        # ==================== 5. 最近活动 ====================

        recent_activities_logs = OperationLog.query.order_by(
            OperationLog.created_at.desc()
        ).limit(10).all()

        formatted_activities = []
        for activity in recent_activities_logs:
            details = activity.details or ''
            details_lower = details.lower()
            
            # 智能判断状态
            if 'fail' in details_lower or 'error' in details_lower:
                status_text = '失败'
                status_color = 'danger'
            elif 'success' in details_lower or '完成' in details_lower:
                status_text = '成功'
                status_color = 'success'
            else:
                status_text = '成功'
                status_color = 'success'
            
            # ==================== 格式化时间（UTC 转北京时间） ====================
            if activity.created_at:
                if activity.created_at.tzinfo is None:
                    utc_time = activity.created_at.replace(tzinfo=timezone.utc)
                else:
                    utc_time = activity.created_at.astimezone(timezone.utc)
                beijing_time = utc_time.astimezone(beijing_tz)
                timestamp_str = beijing_time.strftime('%Y-%m-%d %H:%M')
            else:
                timestamp_str = '--:--'
            
            # 获取设备类型（如果是设备操作）
            device_type = None
            if activity.resource_type == 'device' and activity.resource_id:
                device = Device.query.get(activity.resource_id)
                if device:
                    device_type = device.device_type
            
            formatted_activities.append({
                'timestamp': timestamp_str,
                'type': activity.resource_type,
                'name': activity.resource_name,
                'action': activity.operation_type,
                'status': status_text,
                'status_color': status_color,
                'user': activity.username or '系统',
                'device_type': device_type
            })

        # ==================== 5.5 获取最后检测时间 ====================
        # 获取最新一次设备检测时间
        #from models.models import Device
        last_device = Device.query.order_by(Device.last_checked.desc()).first()
        if last_device and last_device.last_checked:
            # 如果是 datetime 对象，转换为北京时间字符串
            if hasattr(last_device.last_checked, 'strftime'):
                # 如果 last_checked 是 naive datetime，添加时区信息
                if last_device.last_checked.tzinfo is None:
                    utc_time = last_device.last_checked.replace(tzinfo=timezone.utc)
                    beijing_time = utc_time.astimezone(beijing_tz)
                else:
                    beijing_time = last_device.last_checked.astimezone(beijing_tz)
                last_check_time = beijing_time.strftime('%Y-%m-%d %H:%M')
            else:
                last_check_time = str(last_device.last_checked)
        else:
            last_check_time = '从未检测'

        # ==================== 5.6 今日告警统计 ====================
        today_start = current_date.replace(hour=0, minute=0, second=0, microsecond=0)
        # 转换为 UTC 用于数据库查询
        today_start_utc = today_start.astimezone(timezone.utc).replace(tzinfo=None)

        today_alerts = AlertEvent.query.filter(
            AlertEvent.status == 'active',
            AlertEvent.last_occurred >= today_start_utc
        ).count()

        last_alert = AlertEvent.query.filter(
            AlertEvent.status == 'active'
        ).order_by(AlertEvent.last_occurred.desc()).first()

        if last_alert and last_alert.last_occurred:
            if last_alert.last_occurred.tzinfo is None:
                last_alert_time = (last_alert.last_occurred.replace(tzinfo=timezone.utc)
                                   .astimezone(beijing_tz).strftime('%H:%M'))
            else:
                last_alert_time = last_alert.last_occurred.astimezone(beijing_tz).strftime('%H:%M')
        else:
            last_alert_time = None

        # ==================== 5.7 设备分组统计（关联 device_groups / device_group_members） ====================
        group_stats = db.session.query(
            DeviceGroup.id,
            DeviceGroup.name,
            DeviceGroup.color,
            DeviceGroup.icon,
            func.count(Device.id).label('count')
        ).join(
            device_group_members, device_group_members.c.group_id == DeviceGroup.id
        ).join(
            Device, and_(
                Device.id == device_group_members.c.device_id,
                Device.is_decommissioned == False
            )
        ).group_by(
            DeviceGroup.id, DeviceGroup.name, DeviceGroup.color, DeviceGroup.icon
        ).order_by(func.count(Device.id).desc()).limit(8).all()

        top_groups = [
            {
                'id': g.id,
                'name': g.name,
                'color': g.color or '#2a78d6',
                'icon': g.icon or 'fa-folder',
                'count': g.count
            }
            for g in group_stats
        ]

        # 未分组设备数量（用于引导补充资产归属）
        grouped_device_ids = select(device_group_members.c.device_id).distinct()
        ungrouped_devices = Device.query.filter(
            ~Device.id.in_(grouped_device_ids),
            Device.is_decommissioned == False
        ).count()
        total_groups = DeviceGroup.query.count()

        # ==================== 5.8 监控记录统计（关联 device_monitor_logs） ====================
        monitor_trend_days = 7
        trend_start_utc = (current_date - timedelta(days=monitor_trend_days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(timezone.utc).replace(tzinfo=None)

        monitor_day_rows = db.session.query(
            func.date(DeviceMonitorLog.created_at).label('day'),
            DeviceMonitorLog.is_online,
            func.count(DeviceMonitorLog.id).label('count')
        ).filter(DeviceMonitorLog.created_at >= trend_start_utc).group_by(
            func.date(DeviceMonitorLog.created_at),
            DeviceMonitorLog.is_online
        ).all()

        day_index = {}
        for day, is_online, count in monitor_day_rows:
            day_key = day.strftime('%Y-%m-%d') if hasattr(day, 'strftime') else str(day)
            if day_key not in day_index:
                day_index[day_key] = {'online': 0, 'offline': 0}
            if is_online:
                day_index[day_key]['online'] += count
            else:
                day_index[day_key]['offline'] += count

        monitor_trend = []
        for offset in range(monitor_trend_days - 1, -1, -1):
            day = current_date - timedelta(days=offset)
            day_key = day.strftime('%Y-%m-%d')
            day_data = day_index.get(day_key, {'online': 0, 'offline': 0})
            monitor_trend.append({
                'date': day.strftime('%m-%d'),
                'online': day_data['online'],
                'offline': day_data['offline']
            })

        # 最近设备状态变更
        recent_monitor_logs = DeviceMonitorLog.query.order_by(
            DeviceMonitorLog.created_at.desc()
        ).limit(8).all()

        recent_status_changes = []
        for log in recent_monitor_logs:
            device = Device.query.get(log.device_id) if log.device_id else None
            ts_str = '--:--'
            if log.created_at:
                if log.created_at.tzinfo is None:
                    ts = log.created_at.replace(tzinfo=timezone.utc).astimezone(beijing_tz)
                else:
                    ts = log.created_at.astimezone(beijing_tz)
                ts_str = ts.strftime('%m-%d %H:%M')
            recent_status_changes.append({
                'time': ts_str,
                'device_id': log.device_id,
                'device_name': device.name if device else f"#{log.device_id}",
                'device_ip': log.device_ip,
                'old_status': log.old_status or '未知',
                'new_status': log.new_status or '未知',
                'online': bool(log.is_online),
                'error': log.error_message or '',
                'monitor_type': log.monitor_type or ''
            })

        # 监控汇总
        monitor_summary = {
            'total_logs': DeviceMonitorLog.query.count(),
            'last_check': last_check_time,
            'recent_online': DeviceMonitorLog.query.filter(
                DeviceMonitorLog.is_online == True,
                DeviceMonitorLog.created_at >= trend_start_utc
            ).count(),
            'recent_offline': DeviceMonitorLog.query.filter(
                DeviceMonitorLog.is_online == False,
                DeviceMonitorLog.created_at >= trend_start_utc
            ).count()
        }

        # ==================== 5.9 发现任务统计（关联 discovery_tasks） ====================
        discovery_tasks = DiscoveryTask.query.order_by(
            DiscoveryTask.created_at.desc()
        ).limit(5).all()
        discovery_stats = {
            'total_tasks': DiscoveryTask.query.count(),
            'enabled_tasks': DiscoveryTask.query.filter(
                DiscoveryTask.enabled == True
            ).count(),
            'total_discovered': DiscoveryTask.query.with_entities(
                func.coalesce(func.sum(DiscoveryTask.discovered_count), 0)
            ).scalar() or 0
        }

        recent_discovery = []
        for task in discovery_tasks:
            last_run_str = None
            if task.last_run:
                if task.last_run.tzinfo is None:
                    last_run_dt = task.last_run.replace(tzinfo=timezone.utc).astimezone(beijing_tz)
                else:
                    last_run_dt = task.last_run.astimezone(beijing_tz)
                last_run_str = last_run_dt.strftime('%m-%d %H:%M')
            recent_discovery.append({
                'id': task.id,
                'name': task.name,
                'status': task.status or 'idle',
                'enabled': bool(task.enabled),
                'last_run': last_run_str,
                'discovered_count': task.discovered_count or 0,
                'success_count': task.success_count or 0,
                'fail_count': task.fail_count or 0,
                'progress': task.progress or 0,
            })

        # ==================== 5.10 接口与维保关联统计 ====================
        interface_count = Interface.query.count()
        warranty_expiring_count = Device.query.filter(
            Device.warranty_expiry.isnot(None),
            Device.warranty_expiry <= (current_date + timedelta(days=90)).date(),
            Device.warranty_expiry >= current_date.date(),
            Device.is_decommissioned == False
        ).count()
        warranty_expired_count = Device.query.filter(
            Device.warranty_expiry.isnot(None),
            Device.warranty_expiry < current_date.date(),
            Device.is_decommissioned == False
        ).count()

        # ==================== 6. 构建统计数据字典 ====================
        stats = {
            'total_devices': total_devices,
            'online_devices': online_devices,
            'offline_devices': offline_devices,
            'fault_devices': fault_devices,
            'today_alerts': today_alerts,
            'last_alert_time': last_alert_time,
            'new_devices_this_month': new_devices_this_month,
            'online_rate': round(online_rate, 1),
            'total_locations': total_locations,
            'data_center_locations': data_center_locations,
            'total_cabinets': total_cabinets,
            'cabinet_avg_usage': round(cabinet_avg_usage, 1),
            'total_groups': total_groups,
            'ungrouped_devices': ungrouped_devices,
            'interface_count': interface_count,
            'warranty_expiring_count': warranty_expiring_count,
            'warranty_expired_count': warranty_expired_count,
            'total_monitor_logs': monitor_summary['total_logs'],
            'recent_online': monitor_summary['recent_online'],
            'recent_offline': monitor_summary['recent_offline']
        }

        # ==================== 7. 系统状态 ====================
        import psutil
        system_status = {
            'load_percent': psutil.cpu_percent(interval=0.5) if hasattr(psutil, 'cpu_percent') else 0,
            'db_connected': True,
            'monitoring_running': True,
            'disk_usage': f"{psutil.disk_usage('/').used // (1024**3)}GB/{psutil.disk_usage('/').total // (1024**3)}GB" if hasattr(psutil, 'disk_usage') else '0GB/0GB',
            'disk_percent': psutil.disk_usage('/').percent if hasattr(psutil, 'disk_usage') else 0
        }
        
        # ==================== 8. 告警信息（关联真实告警数据） ====================
        alert_events = AlertEvent.query.filter(
            AlertEvent.status == 'active',
            AlertEvent.suppressed == False
        ).order_by(AlertEvent.last_occurred.desc()).limit(8).all()

        severity_map = {
            'critical': ('严重', 'critical'),
            'error': ('错误', 'error'),
            'warning': ('警告', 'warning'),
            'info': ('提示', 'info'),
        }
        alerts = []
        for event in alert_events:
            device = Device.query.get(event.device_id) if event.device_id else None
            ts_str = '--:--'
            if event.last_occurred:
                if event.last_occurred.tzinfo is None:
                    ts = event.last_occurred.replace(tzinfo=timezone.utc).astimezone(beijing_tz)
                else:
                    ts = event.last_occurred.astimezone(beijing_tz)
                ts_str = ts.strftime('%m-%d %H:%M')
            level_display, level_class = severity_map.get(
                event.severity, (event.severity or '未知', 'warning')
            )
            alerts.append({
                'id': event.id,
                'title': event.title,
                'description': event.message,
                'level': event.severity,
                'level_display': level_display,
                'level_class': level_class,
                'time': ts_str,
                'occurrence_count': event.occurrence_count,
                'device_id': event.device_id,
                'device_name': device.name if device else None,
                'device_link': url_for('device.device_detail', id=event.device_id) if event.device_id else '#',
                'alert_link': url_for('alert.active_alerts'),
            })
        
        # 记录日志
        current_app.logger.debug(f"Dashboard stats: {stats}")
        return render_template(
            'dashboard.html',
            current_date=current_date,
            stats=stats,
            recent_activities=formatted_activities,
            device_type_distribution=device_type_distribution,
            system_status=system_status,
            alerts=alerts,
            cabinet_status=cabinet_status_top5,
            last_check_time=last_check_time,  # 添加这个变量
            top_groups=top_groups,
            monitor_trend=monitor_trend,
            recent_status_changes=recent_status_changes,
            monitor_summary=monitor_summary,
            discovery_stats=discovery_stats,
            recent_discovery=recent_discovery
        )

    except Exception as e:
        current_app.logger.error(f"Dashboard error: {str(e)}", exc_info=True)
        
        # 返回基本页面，带上错误信息
        beijing_tz = pytz.timezone('Asia/Shanghai')
        return render_template(
            'dashboard.html',
            current_date=datetime.now(beijing_tz),
            stats={
                'total_devices': 0,
                'online_devices': 0,
                'offline_devices': 0,
                'fault_devices': 0,
                'today_alerts': 0,
                'last_alert_time': None,
                'new_devices_this_month': 0,
                'online_rate': 0,
                'total_locations': 0,
                'data_center_locations': 0,
                'total_cabinets': 0,
                'cabinet_avg_usage': 0,
                'total_groups': 0,
                'ungrouped_devices': 0,
                'interface_count': 0,
                'warranty_expiring_count': 0,
                'warranty_expired_count': 0,
                'total_monitor_logs': 0,
                'recent_online': 0,
                'recent_offline': 0
            },
            device_type_distribution={},
            recent_activities=[],
            top_groups=[],
            monitor_trend=[],
            recent_status_changes=[],
            monitor_summary={
                'total_logs': 0,
                'last_check': '从未检测',
                'recent_online': 0,
                'recent_offline': 0
            },
            discovery_stats={
                'total_tasks': 0,
                'enabled_tasks': 0,
                'total_discovered': 0
            },
            recent_discovery=[],
            system_status={
                'load_percent': 0,
                'db_connected': False,
                'monitoring_running': False,
                'disk_usage': '0GB/0GB',
                'disk_percent': 0
            },
            alerts=[],
            cabinet_status=[],
            error_message=str(e)
        )


# ==================== 备选方案：使用更清晰的查询方式 ====================
# 如果上述查询仍有问题，可以使用以下分步查询方式（性能略低但更清晰）

def get_cabinet_status_alternative():
    """
    备选方案：分步查询机柜状态
    避免复杂的 JOIN 导致的笛卡尔积问题
    """
    # 1. 获取所有机柜及其关联的位置信息
    cabinets = db.session.query(
        Cabinet.id,
        Cabinet.name,
        Cabinet.height_u,
        Cabinet.location_id
    ).all()
    
    # 2. 批量获取所有位置信息（一次查询）
    location_ids = [c.location_id for c in cabinets if c.location_id]
    locations = {}
    if location_ids:
        location_query = db.session.query(Location.id, Location.name).filter(
            Location.id.in_(location_ids)
        ).all()
        locations = {loc.id: loc.name for loc in location_query}
    
    # 3. 批量获取所有机柜的设备数量（一次查询）
    cabinet_ids = [c.id for c in cabinets]
    device_counts = {}
    if cabinet_ids:
        count_query = db.session.query(
            Device.cabinet_id,
            func.count(Device.id).label('count')
        ).filter(Device.cabinet_id.in_(cabinet_ids)).group_by(Device.cabinet_id).all()
        device_counts = {cabinet_id: count for cabinet_id, count in count_query}
    
    # 4. 组装结果
    cabinet_status = []
    total_usage = 0
    cabinet_count_with_usage = 0
    
    for cabinet in cabinets:
        used_slots = device_counts.get(cabinet.id, 0)
        location_name = locations.get(cabinet.location_id, '未指定')
        
        if cabinet.height_u and cabinet.height_u > 0:
            usage_percent = (used_slots / cabinet.height_u) * 100
            total_usage += usage_percent
            cabinet_count_with_usage += 1
        else:
            usage_percent = 0
        
        cabinet_status.append({
            'name': cabinet.name,
            'location': location_name,
            'total_slots': cabinet.height_u or 42,
            'used_slots': used_slots,
            'usage_percent': round(usage_percent, 1)
        })
    
    cabinet_avg_usage = total_usage / cabinet_count_with_usage if cabinet_count_with_usage > 0 else 0
    
    return cabinet_status, cabinet_avg_usage
