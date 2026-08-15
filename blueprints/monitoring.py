# blueprints/monitoring.py
from datetime import datetime, timedelta,timezone
import json
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, desc, and_, or_
import random

# 导入模型
from models.models import (
    Device, Interface, MonitorData, AlertEvent, AlertRule, MonitorSetting,MonitorSchedule,NotificationConfig,
    InterfaceMonitorData, ConnectionPath, Location, Cabinet,db,DeviceMonitorConfig, MonitoringSetting,db,
    PerformanceMetric 
)
from models.config_models import GlobalParameter
from models.settings_models import SystemConfig
from models.monitoring import AlertHistory,DeviceConfig
from utils.utils import get_device_snmp_data,save_discovered_interfaces,snmp_discover_interfaces_real
from utils.tasks import poll_all_devices_interfaces
import logging
from utils.audit import log_audit
from utils.permission import permission_required
logger = logging.getLogger(__name__)


def send_test_notification(notification):
    """
    根据通知配置发送测试消息
    返回 (success: bool, message: str)
    """
    from services.notification_service import send_notification
    return send_notification(notification)



# 初始化蓝图
monitoring_bp = Blueprint('monitoring', __name__, url_prefix='/monitoring')



# ========== 通知配置删除 ==========
@monitoring_bp.route('/notifications/<int:notification_id>/delete')
@login_required
@permission_required('monitor:view')
def notification_delete(notification_id):
    """删除通知配置"""
    from flask import flash, redirect, url_for
    from app import db
    from datetime import datetime, timezone

    notification = NotificationConfig.query.get_or_404(notification_id)
    
    try:
        # 删除记录
        db.session.delete(notification)
        db.session.commit()
        flash(f'通知配置 "{notification.name}" 已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'danger')
    
    return redirect(url_for('monitoring.notification_list'))

# ========== 通知配置启用/禁用切换 ==========
@monitoring_bp.route('/notifications/<int:notification_id>/toggle')
@login_required
@permission_required('monitor:view')
def notification_toggle(notification_id):
    """切换通知配置的启用状态"""
    from flask import flash, redirect, url_for
    from app import db
    from datetime import datetime, timezone

    notification = NotificationConfig.query.get_or_404(notification_id)
    
    # 切换启用状态
    notification.enabled = not notification.enabled
    notification.updated_at = datetime.now(timezone.utc)
    
    try:
        db.session.commit()
        status = "启用" if notification.enabled else "禁用"
        flash(f'通知配置 "{notification.name}" 已{status}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'切换状态失败: {str(e)}', 'danger')
    
    return redirect(url_for('monitoring.notification_list'))





# ========== 实时监控 ==========


@monitoring_bp.route('/real_time')
@login_required
@permission_required('monitor:view')
def real_time_monitor():
    """实时监控页面"""
    # 获取所有设备
    devices = Device.query.order_by(Device.name).all()
    
    # 获取监控设置
    monitoring_settings = MonitoringSetting.query.all()
    settings_dict = {}
    for setting in monitoring_settings:
        settings_dict[setting.setting_key] = setting.get_value()
    
    return render_template('monitoring/real_time.html',
                         devices=devices,
                         monitoring_settings=settings_dict)



@monitoring_bp.route('/get_snmp_data')
@login_required
@permission_required('monitor:view')
def get_snmp_data():
    """获取指定设备的实时 SNMP 数据（JSON 格式）"""
    device_id = request.args.get('device_id', type=int)
    if not device_id:
        return jsonify({'success': False, 'message': '缺少设备ID'}), 400

    device = Device.query.get(device_id)
    if not device:
        return jsonify({'success': False, 'message': '设备不存在'}), 404

    # 检查设备是否配置了管理 IP 和 SNMP 团体字
    if not device.management_ip or not device.snmp_community:
        return jsonify({'success': False, 'message': '设备未配置管理IP或SNMP团体字'}), 400

    try:
        # 调用 utils.py 中的 SNMP 采集函数
        data = get_device_snmp_data(device)
        # 如果采集成功，更新设备的最后检查时间
        device.last_checked = datetime.now(timezone.utc)
        db.session.commit()
        log_audit(
            action='execute',
            resource_type='monitor_data',
            resource_id=device_id,
            message=f'保存SNMP数据: {device.name}',
            user_id=current_user.id
        )
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        current_app.logger.error(f"SNMP采集失败 (设备 {device.name}): {str(e)}")
        return jsonify({'success': False, 'message': f'SNMP采集失败: {str(e)}'}), 500


@monitoring_bp.route('/save_snmp_data', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def save_snmp_data():
    """将当前设备的 SNMP 数据保存到数据库（更新设备字段）"""
    data = request.get_json()
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'success': False, 'message': '缺少设备ID'}), 400

    device = Device.query.get(device_id)
    if not device:
        return jsonify({'success': False, 'message': '设备不存在'}), 404

    if not device.management_ip or not device.snmp_community:
        return jsonify({'success': False, 'message': '设备未配置管理IP或SNMP团体字'}), 400

    try:
        # 重新采集一次最新数据（确保保存的是最新值）
        snmp_data = snmp.get_device_snmp_data(
            ip=device.management_ip,
            community=device.snmp_community,
            version=device.snmp_version or 2
        )

        # 更新设备字段
        device.cpu_usage = snmp_data.get('cpu_usage')
        device.memory_usage = snmp_data.get('memory_usage')
        device.disk_usage = snmp_data.get('disk_usage')
        device.temperature = snmp_data.get('temperature')
        device.power_consumption = snmp_data.get('power_consumption')
        device.power_supply = snmp_data.get('power_supply')
        device.last_checked = datetime.now(timezone.utc)
        db.session.commit()

        log_audit(
            action='update',
            resource_type='monitor_data',
            resource_id=device_id,
            message=f'保存SNMP数据: {device.name}',
            user_id=current_user.id
        )

        return jsonify({'success': True, 'message': '数据保存成功', 'data': snmp_data})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"保存SNMP数据失败 (设备 {device.name}): {str(e)}")
        return jsonify({'success': False, 'message': f'保存失败: {str(e)}'}), 500

def get_device_realtime_data(device):
    """获取设备的实时数据 - 从数据库读取"""
    # 查询最新的 MonitorData 记录
    latest = MonitorData.query.filter_by(device_id=device.id)\
        .order_by(MonitorData.collected_at.desc()).first()

    if latest:
        # 计算运行时间文本
        uptime_str = ''
        if latest.uptime:
            days = latest.uptime // 86400
            hours = (latest.uptime % 86400) // 3600
            mins = (latest.uptime % 3600) // 60
            uptime_str = f'{days}天{hours}小时{mins}分钟'

        return {
            'id': device.id,
            'name': device.name,
            'status': device.status,
            'type': device.device_type,
            'ip': device.management_ip or device.ip_address or 'N/A',
            'location': device.location.name if device.location else '未分配',
            'uptime': uptime_str or '未知',
            'cpu_usage': round(latest.cpu_usage, 2) if latest.cpu_usage is not None else None,
            'memory_usage': round(latest.memory_usage, 2) if latest.memory_usage is not None else None,
            'network_usage': None,
            'disk_usage': round(latest.disk_usage, 2) if latest.disk_usage is not None else None,
            'temperature': round(latest.temperature, 2) if latest.temperature is not None else None,
            'fan_speed': None,
            'power_usage': round(latest.power_consumption, 2) if latest.power_consumption is not None else None,
            'last_check': latest.collected_at.isoformat() if latest.collected_at else None,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

    # 无监控数据时返回基本信息
    return {
        'id': device.id,
        'name': device.name,
        'status': device.status,
        'type': device.device_type,
        'ip': device.management_ip or device.ip_address or 'N/A',
        'location': device.location.name if device.location else '未分配',
        'cpu_usage': None,
        'memory_usage': None,
        'network_usage': None,
        'disk_usage': None,
        'temperature': None,
        'fan_speed': None,
        'power_usage': None,
        'uptime': '未知',
        'last_check': device.last_checked.isoformat() if device.last_checked else None,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
def _update_config_from_form(config, form_data):
    """从表单数据更新配置对象（公共逻辑）"""
    # 基本开关
    config.enabled = 'enabled' in form_data
    config.enable_ping = 'enable_ping' in form_data
    config.enable_snmp = 'enable_snmp' in form_data
    config.enable_api = 'enable_api' in form_data
    config.enable_ssh = form_data.get('enable_ssh', 'no')

    # 间隔与超时
    config.ping_interval = int(form_data.get('ping_interval', 30))
    config.ping_timeout = float(form_data.get('ping_timeout', 2.0))
    config.snmp_interval = int(form_data.get('snmp_interval', 300))
    config.snmp_timeout = float(form_data.get('snmp_timeout', 3.0))
    config.ssh_interval = int(form_data.get('ssh_interval', 600))
    config.ssh_timeout = float(form_data.get('ssh_timeout', 5.0))
    config.api_interval = int(form_data.get('api_interval', 600))
    config.api_timeout = float(form_data.get('api_timeout', 10.0))
    config.retry_count = int(form_data.get('retry_count', 1))
    config.retry_interval = int(form_data.get('retry_interval', 1))

    # SNMP 配置
    config.snmp_version = form_data.get('snmp_version', '2c')
    config.snmp_community = form_data.get('snmp_community', 'public')
    config.snmp_username = form_data.get('snmp_username') or None
    config.snmp_auth_protocol = form_data.get('snmp_auth_protocol') or None
    config.snmp_priv_protocol = form_data.get('snmp_priv_protocol') or None
    # 密码字段：仅当填写时才更新（留空则不修改）
    if form_data.get('snmp_auth_password'):
        config.snmp_auth_password = form_data['snmp_auth_password']
    if form_data.get('snmp_priv_password'):
        config.snmp_priv_password = form_data['snmp_priv_password']

    # SSH 配置
    config.ssh_username = form_data.get('ssh_username') or None
    if form_data.get('ssh_password'):
        config.ssh_password = form_data['ssh_password']
    config.ssh_port = int(form_data.get('ssh_port', 22))
    config.ssh_key_file = form_data.get('ssh_key_file') or None

    # API 配置
    config.api_url = form_data.get('api_url') or None
    config.api_method = form_data.get('api_method', 'GET')
    config.api_auth_type = form_data.get('api_auth_type') or None
    config.api_auth_value = form_data.get('api_auth_value') or None
    # 处理 JSON 字段
    headers_str = form_data.get('api_headers', '{}').strip()
    if headers_str:
        try:
            json.loads(headers_str)  # 验证 JSON 格式
            config.api_headers = headers_str
        except:
            config.api_headers = '{}'
    else:
        config.api_headers = '{}'

    body_str = form_data.get('api_body', '{}').strip()
    if body_str:
        try:
            json.loads(body_str)
            config.api_body = body_str
        except:
            config.api_body = '{}'
    else:
        config.api_body = '{}'

    # 监控指标 JSON
    metrics_str = form_data.get('monitor_metrics', '{}').strip()
    if metrics_str:
        try:
            json.loads(metrics_str)
            config.monitor_metrics = metrics_str
        except:
            config.monitor_metrics = '{}'
    else:
        config.monitor_metrics = '{}'

    config.inherit_alerts = 'inherit_alerts' in form_data

    return config
# ========== 设备状态 ==========
@monitoring_bp.route('/device_status')
@login_required
@permission_required('monitor:view')
def device_status():
    """设备状态页面"""
    # 获取查询参数
    status_filter = request.args.get('status', 'all')
    device_type = request.args.get('type', 'all')
    location_id = request.args.get('location_id', type=int)
    
    # 构建查询
    query = Device.query
    
    if status_filter != 'all':
        query = query.filter(Device.status == status_filter)
    
    if device_type != 'all':
        query = query.filter(Device.device_type == device_type)
    
    if location_id:
        query = query.filter(Device.location_id == location_id)
    
    # 排序
    sort_by = request.args.get('sort_by', 'name')
    order = request.args.get('order', 'asc')
    
    if sort_by == 'name':
        query = query.order_by(Device.name.asc() if order == 'asc' else Device.name.desc())
    elif sort_by == 'status':
        query = query.order_by(Device.status.asc() if order == 'asc' else Device.status.desc())
    elif sort_by == 'last_checked':
        query = query.order_by(
            Device.last_checked.asc() if order == 'asc' else Device.last_checked.desc()
        )
    
    devices = query.all()
    
    # 获取所有位置和类型用于筛选
    locations = Location.query.all()
    device_types = db.session.query(Device.device_type).distinct().all()
    
    # 计算统计
    status_counts = {
        'online': Device.query.filter_by(status='online').count(),
        'offline': Device.query.filter_by(status='offline').count(),
        'warning': Device.query.filter_by(status='warning').count(),
        'unknown': Device.query.filter_by(status='unknown').count(),
        'maintenance': Device.query.filter_by(status='maintenance').count(),
    }
    
    return render_template('monitoring/device_status.html',
                         devices=devices,
                         locations=locations,
                         device_types=[t[0] for t in device_types],
                         status_counts=status_counts,
                         status_filter=status_filter,
                         device_type_filter=device_type,
                         location_id=location_id,
                         sort_by=sort_by,
                         order=order)

# ========== 性能图表 ==========
@monitoring_bp.route('/performance_charts')
@login_required
@permission_required('monitor:view')
def performance_charts():
    """性能图表页面"""
    # 获取设备ID参数
    device_id = request.args.get('device_id', type=int)
    
    # 获取所有设备用于选择
    devices = Device.query.order_by(Device.name).all()
    
    # 获取时间范围参数
    time_range = request.args.get('time_range', '24h')
    
    # 计算时间范围
    end_time = datetime.now(timezone.utc)
    if time_range == '1h':
        start_time = end_time - timedelta(hours=1)
        interval = 1  # 分钟
    elif time_range == '6h':
        start_time = end_time - timedelta(hours=6)
        interval = 5  # 分钟
    elif time_range == '24h':
        start_time = end_time - timedelta(hours=24)
        interval = 30  # 分钟
    elif time_range == '7d':
        start_time = end_time - timedelta(days=7)
        interval = 6  # 小时
    elif time_range == '30d':
        start_time = end_time - timedelta(days=30)
        interval = 1  # 天
    else:
        start_time = end_time - timedelta(hours=24)
        interval = 30
    
    # 如果有设备ID，获取该设备的监控数据
    chart_data = {}
    if device_id:
        device = Device.query.get_or_404(device_id)
        
        # 查询监控数据
        monitor_records = MonitorData.query.filter(
            MonitorData.device_id == device_id,
            MonitorData.collected_at >= start_time
        ).order_by(MonitorData.collected_at).all()
        
        # 准备图表数据
        timestamps = []
        cpu_data = []
        memory_data = []
        disk_data = []
        ping_data = []
        
        for record in monitor_records:
            timestamps.append(record.collected_at.strftime('%Y-%m-%d %H:%M'))
            cpu_data.append(record.cpu_usage or 0)
            memory_data.append(record.memory_usage or 0)
            disk_data.append(record.disk_usage or 0)
            ping_data.append(record.ping_time or 0)
        
        chart_data = {
            'device': device,
            'timestamps': timestamps,
            'cpu': cpu_data,
            'memory': memory_data,
            'disk': disk_data,
            'ping': ping_data
        }
    
    # 获取所有设备的性能排名
    # 获取最近一小时的平均性能数据
    recent_start = datetime.now(timezone.utc) - timedelta(hours=1)
    
    # 使用子查询获取每个设备的平均CPU使用率
    from sqlalchemy import func
    
    performance_rank = db.session.query(
        Device.id,
        Device.name,
        func.avg(MonitorData.cpu_usage).label('avg_cpu'),
        func.avg(MonitorData.memory_usage).label('avg_memory'),
        func.avg(MonitorData.ping_time).label('avg_ping')
    ).join(MonitorData, Device.id == MonitorData.device_id).filter(
        MonitorData.collected_at >= recent_start,
        MonitorData.cpu_usage.isnot(None)
    ).group_by(Device.id, Device.name).order_by(
        func.avg(MonitorData.cpu_usage).desc()
    ).limit(20).all()
    
    return render_template('monitoring/performance_charts.html',
                         devices=devices,
                         chart_data=chart_data,
                         device_id=device_id,
                         time_range=time_range,
                         performance_rank=performance_rank)

# ========== 接口监控 ==========
"""
@monitoring_bp.route('/interface_monitor')
@login_required
def interface_monitor():
    #接口监控页面
    # 获取设备ID参数
    device_id = request.args.get('device_id', type=int)
    
    # 获取所有设备
    devices = Device.query.order_by(Device.name).all()
    
    # 获取接口数据
    interfaces = []
    interface_stats = {}
    
    if device_id:
        device = Device.query.get_or_404(device_id)
        interfaces = Interface.query.filter_by(device_id=device_id).all()
        
        # 获取接口监控数据
        for interface in interfaces:
            latest_data = InterfaceMonitorData.query.filter_by(
                interface_id=interface.id
            ).order_by(InterfaceMonitorData.collected_at.desc()).first()
            
            if latest_data:
                interface_stats[interface.id] = {
                    'bytes_in': latest_data.bytes_in,
                    'bytes_out': latest_data.bytes_out,
                    'bandwidth_usage': latest_data.bandwidth_usage,
                    'admin_status': latest_data.admin_status,
                    'oper_status': latest_data.oper_status,
                    'last_updated': latest_data.collected_at
                }
    
    # 获取连接关系
    connections = []
    if device_id:
        connections = ConnectionPath.query.filter(
            or_(
                ConnectionPath.source_device_id == device_id,
                ConnectionPath.target_device_id == device_id
            )
        ).all()
    
    return render_template('monitoring/interface_monitor.html',
                         devices=devices,
                         interfaces=interfaces,
                         interface_stats=interface_stats,
                         connections=connections,
                         device_id=device_id)
"""


# ========== 历史数据 ==========
@monitoring_bp.route('/history_data')
@login_required
@permission_required('monitor:view')
def history_data():
    """历史数据查询页面"""
    # 获取查询参数
    device_id = request.args.get('device_id', type=int)
    metric_type = request.args.get('metric_type', 'cpu')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # 处理日期
    if not start_date:
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
    end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
    
    # 获取所有设备
    devices = Device.query.order_by(Device.name).all()
    
    # 查询历史数据
    history_data = []
    if device_id:
        query = MonitorData.query.filter(
            MonitorData.device_id == device_id,
            MonitorData.collected_at >= start_datetime,
            MonitorData.collected_at <= end_datetime
        )
        
        # 根据指标类型筛选
        if metric_type == 'cpu':
            query = query.filter(MonitorData.cpu_usage.isnot(None))
        elif metric_type == 'memory':
            query = query.filter(MonitorData.memory_usage.isnot(None))
        elif metric_type == 'disk':
            query = query.filter(MonitorData.disk_usage.isnot(None))
        elif metric_type == 'ping':
            query = query.filter(MonitorData.ping_time.isnot(None))
        
        history_data = query.order_by(MonitorData.collected_at.desc()).all()
    
    # 获取数据统计
    stats = {}
    if device_id and history_data:
        values = []
        for data in history_data:
            if metric_type == 'cpu':
                values.append(data.cpu_usage)
            elif metric_type == 'memory':
                values.append(data.memory_usage)
            elif metric_type == 'disk':
                values.append(data.disk_usage)
            elif metric_type == 'ping':
                values.append(data.ping_time)
        
        if values:
            stats = {
                'avg': sum(values) / len(values),
                'max': max(values),
                'min': min(values),
                'count': len(values)
            }
    
    return render_template('monitoring/history_data.html',
                         devices=devices,
                         history_data=history_data,
                         stats=stats,
                         device_id=device_id,
                         metric_type=metric_type,
                         start_date=start_date,
                         end_date=end_date)

@monitoring_bp.route('/alerts')
@login_required
@permission_required('monitor:view')
def alerts():
    """告警管理页面"""
    # 获取所有设备
    devices = Device.query.order_by(Device.name).all()
    
    # 获取告警设置
    alert_settings = MonitoringSetting.query.filter_by(category='alerts').all()
    settings_dict = {}
    for setting in alert_settings:
        settings_dict[setting.setting_key] = setting.get_value()
    
    return render_template('monitoring/alerts.html',
                         devices=devices,
                         alert_settings=settings_dict)

@monitoring_bp.route('/metrics')
@login_required
@permission_required('monitor:view')
def metrics():
    """指标管理页面"""
    # 获取性能指标
    metrics = PerformanceMetric.query.order_by(PerformanceMetric.timestamp.desc()).limit(100).all()
    
    # 按设备分组
    devices = Device.query.order_by(Device.name).all()
    
    return render_template('monitoring/metrics.html',
                         metrics=metrics,
                         devices=devices)
# ========== API接口 ==========

@monitoring_bp.route('/api/real_time_data')
@login_required
@permission_required('monitor:view')
def api_real_time_data():
    """获取实时监控数据"""
    # 获取最近5分钟的监控数据
    five_minutes_ago = datetime.now(timezone.utc)- timedelta(minutes=5)
    
    # 获取设备状态
    devices = Device.query.all()
    
    # 构建返回数据
    data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'device_count': len(devices),
        'devices': [],
        'alerts': []
    }
    
    for device in devices:
        # 获取最新监控数据
        latest_data = MonitorData.query.filter_by(device_id=device.id)\
            .order_by(MonitorData.collected_at.desc()).first()
        
        device_data = {
            'id': device.id,
            'name': device.name,
            'ip': device.management_ip or device.ip_address,
            'status': device.status,
            'type': device.device_type,
            'last_checked': device.last_checked.isoformat() if device.last_checked else None,
        }
        
        if latest_data:
            device_data.update({
                'cpu': latest_data.cpu_usage,
                'memory': latest_data.memory_usage,
                'disk': latest_data.disk_usage,
                'ping': latest_data.ping_time,
                'is_reachable': latest_data.is_reachable,
                'data_timestamp': latest_data.collected_at.isoformat()
            })
        
        data['devices'].append(device_data)
    
    # 获取活跃告警
    active_alerts = AlertEvent.query.filter_by(status='active')\
        .order_by(AlertEvent.last_occurred.desc()).limit(20).all()
    
    for alert in active_alerts:
        data['alerts'].append(alert.to_dict())
    
    return jsonify(data)

@monitoring_bp.route('/api/device/<int:device_id>/metrics')
@login_required
@permission_required('monitor:view')
def api_device_metrics(device_id):
    """获取设备监控指标数据"""
    # 获取时间范围参数
    hours = request.args.get('hours', 24, type=int)
    metric = request.args.get('metric', 'cpu')
    
    # 计算时间范围
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    
    # 查询数据
    query = MonitorData.query.filter(
        MonitorData.device_id == device_id,
        MonitorData.collected_at >= start_time,
        MonitorData.collected_at <= end_time
    ).order_by(MonitorData.collected_at)
    
    # 根据指标类型筛选
    if metric == 'cpu':
        query = query.filter(MonitorData.cpu_usage.isnot(None))
        field = 'cpu_usage'
    elif metric == 'memory':
        query = query.filter(MonitorData.memory_usage.isnot(None))
        field = 'memory_usage'
    elif metric == 'disk':
        query = query.filter(MonitorData.disk_usage.isnot(None))
        field = 'disk_usage'
    elif metric == 'ping':
        query = query.filter(MonitorData.ping_time.isnot(None))
        field = 'ping_time'
    elif metric == 'network_in':
        query = query.filter(MonitorData.network_in.isnot(None))
        field = 'network_in'
    elif metric == 'network_out':
        query = query.filter(MonitorData.network_out.isnot(None))
        field = 'network_out'
    else:
        return jsonify({'error': 'Invalid metric type'}), 400
    
    data = query.all()
    
    # 构建响应数据
    result = {
        'device_id': device_id,
        'metric': metric,
        'data': []
    }
    
    for record in data:
        result['data'].append({
            'timestamp': record.collected_at.isoformat(),
            'value': getattr(record, field)
        })
    
    return jsonify(result)

@monitoring_bp.route('/api/interface/<int:interface_id>/traffic')
@login_required
@permission_required('monitor:view')
def api_interface_traffic(interface_id):
    """获取接口流量数据"""
    # 获取时间范围参数
    hours = request.args.get('hours', 1, type=int)
    
    # 计算时间范围
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    
    # 查询接口监控数据
    data = InterfaceMonitorData.query.filter(
        InterfaceMonitorData.interface_id == interface_id,
        InterfaceMonitorData.collected_at >= start_time,
        InterfaceMonitorData.collected_at <= end_time
    ).order_by(InterfaceMonitorData.collected_at).all()
    
    # 构建响应数据
    result = {
        'interface_id': interface_id,
        'data': []
    }
    
    for record in data:
        result['data'].append({
            'timestamp': record.collected_at.isoformat(),
            'bytes_in': record.bytes_in,
            'bytes_out': record.bytes_out,
            'bandwidth_usage': record.bandwidth_usage,
            'admin_status': record.admin_status,
            'oper_status': record.oper_status
        })
    
    return jsonify(result)

@monitoring_bp.route('/api/status_summary')
@login_required
@permission_required('monitor:view')
def api_status_summary():
    """获取状态汇总（单次 GROUP BY 聚合优化，利用 idx_devices_status 索引）"""
    # 用一条 GROUP BY 替代 6 次独立 COUNT
    status_rows = db.session.query(
        Device.status,
        func.count(Device.id)
    ).filter(
        Device.is_decommissioned == False
    ).group_by(Device.status).all()

    status_map = {row[0]: row[1] for row in status_rows}
    total = sum(status_map.values())
    status_counts = {
        'online': status_map.get('online', 0),
        'offline': status_map.get('offline', 0),
        'warning': status_map.get('warning', 0),
        'unknown': status_map.get('unknown', 0),
        'maintenance': status_map.get('maintenance', 0),
        'total': total
    }

    # 按类型统计
    device_types = db.session.query(
        Device.device_type,
        func.count(Device.id).label('count')
    ).filter(
        Device.is_decommissioned == False
    ).group_by(Device.device_type).all()

    type_counts = {t[0]: t[1] for t in device_types}

    # 获取活跃告警数量
    active_alert_count = AlertEvent.query.filter_by(status='active').count()

    return jsonify({
        'status_counts': status_counts,
        'type_counts': type_counts,
        'active_alerts': active_alert_count,
        'timestamp': datetime.now(timezone.utc).isoformat()
    })

# ========== 全局设置管理 ==========


@monitoring_bp.route('/global-settings', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def global_settings():
    if request.method == 'POST':
        form_action = request.form.get('form_action')
        if form_action == 'add':
            # 处理新建参数逻辑
            key = request.form['setting_key']
            value = request.form['setting_value']
            # ... 验证并保存到 GlobalParameter 表
            db.session.add(GlobalParameter(
                name=key,
                value=value,
                data_type=request.form['setting_type'],
                category=request.form['category'],
                description=request.form.get('description', ''),
                enabled='enabled' in request.form
            ))
            db.session.commit()
            log_audit(
                action='create',
                resource_type='global_parameter',
                resource_id=key,
                message=f'添加全局参数: {key}',
                user_id=current_user.id
            )
            flash('参数添加成功', 'success')
        return redirect(url_for('config.global_settings'))  # 重定向避免重复提交

    # GET 逻辑不变
    categories = db.session.query(GlobalParameter.category).distinct().all()
    category_list = [c[0] for c in categories]
    params_by_category = {
        cat: [p.to_dict() for p in GlobalParameter.query.filter_by(category=cat, enabled=True)]
        for cat in category_list
    }
    return render_template('config/global_settings.html',
                         params_by_category=params_by_category,
                         categories=category_list)


@monitoring_bp.route('/global/save', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def save_global_settings():
    """保存全局设置"""
    try:
        data = request.get_json()
        
        for setting_data in data.get('settings', []):
            setting_key = setting_data.get('key')
            setting_value = setting_data.get('value')
            category = setting_data.get('category', 'general')
            
            # 查找现有设置
            setting = MonitorSetting.query.filter_by(
                setting_key=setting_key, 
                scope='global'
            ).first()
            
            if not setting:
                # 创建新设置
                setting = MonitorSetting(
                    setting_key=setting_key,
                    category=category,
                    scope='global',
                    created_by=current_user.username,
                    is_default=False
                )
                db.session.add(setting)
            
            # 更新设置值
            setting.set_value(setting_value)
            setting.updated_at = datetime.now(timezone.utc)
            setting.updated_by = current_user.username
        
        db.session.commit()

        log_audit(
            action='update',
            resource_type='monitor_setting',
            resource_id='global',
            message='保存全局设置',
            user_id=current_user.id
        )

        return jsonify({
            'success': True,
            'message': '设置保存成功'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'保存设置失败: {str(e)}'
        }), 500

@monitoring_bp.route('/global/<string:key>', methods=['DELETE'])
@login_required
@permission_required('monitor:edit')
def delete_global_setting(key):
    """删除全局设置"""
    try:
        setting = MonitorSetting.query.filter_by(
            setting_key=key, 
            scope='global',
            is_default=False
        ).first()
        
        if not setting:
            return jsonify({
                'success': False,
                'message': '设置不存在或不能删除'
            }), 404
        
        db.session.delete(setting)
        db.session.commit()

        log_audit(
            action='delete',
            resource_type='monitor_setting',
            resource_id=key,
            message=f'删除全局设置: {key}',
            user_id=current_user.id
        )

        return jsonify({
            'success': True,
            'message': '设置删除成功'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'删除设置失败: {str(e)}'
        }), 500

@monitoring_bp.route('/global/reset', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def reset_global_settings():
    """重置全局设置到默认值"""
    try:
        category = request.json.get('category')
        
        # 删除非默认设置
        if category:
            settings = MonitorSetting.query.filter_by(
                category=category,
                scope='global',
                is_default=False
            ).all()
        else:
            settings = MonitorSetting.query.filter_by(
                scope='global',
                is_default=False
            ).all()
        
        for setting in settings:
            db.session.delete(setting)
        
        db.session.commit()

        log_audit(
            action='execute',
            resource_type='monitor_setting',
            resource_id='global',
            message='重置全局设置到默认值',
            user_id=current_user.id
        )

        return jsonify({
            'success': True,
            'message': '设置已重置到默认值'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'重置设置失败: {str(e)}'
        }), 500

# ========== 监控调度管理 ==========
@monitoring_bp.route('/schedules')
@login_required
@permission_required('monitor:view')
def schedule_list():
    """监控调度列表"""
    schedules = MonitorSchedule.query.order_by(MonitorSchedule.name).all()
    
    return render_template('monitoring/schedule_list.html',
                         schedules=schedules)

@monitoring_bp.route('/schedules/create', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def create_schedule():
    """创建监控调度"""
    if request.method == 'POST':
        try:
            data = request.form
            
            schedule = MonitorSchedule(
                name=data.get('name'),
                description=data.get('description'),
                monitor_type=data.get('monitor_type'),
                target_type=data.get('target_type'),
                schedule_type=data.get('schedule_type'),
                enabled=data.get('enabled', 'off') == 'on',
                created_by=current_user.username
            )
            
            # 设置目标值
            target_value = data.get('target_value')
            if target_value:
                schedule.target_value = target_value
            
            # 设置调度参数
            if schedule.schedule_type == 'interval':
                interval = data.get('interval_seconds')
                if interval:
                    schedule.interval_seconds = int(interval)
            elif schedule.schedule_type == 'cron':
                cron_expr = data.get('cron_expression')
                if cron_expr:
                    schedule.cron_expression = cron_expr
            
            # 设置时间窗口
            start_time = data.get('start_time')
            end_time = data.get('end_time')
            weekdays = data.get('weekdays')
            
            if start_time:
                schedule.start_time = datetime.strptime(start_time, '%H:%M').time()
            if end_time:
                schedule.end_time = datetime.strptime(end_time, '%H:%M').time()
            if weekdays:
                schedule.weekdays = weekdays
            
            # 设置配置
            config_data = {}
            for key in request.form:
                if key.startswith('config_'):
                    config_key = key[7:]  # 去掉'config_'前缀
                    config_data[config_key] = request.form[key]
            
            schedule.set_config(config_data)
            
            db.session.add(schedule)
            db.session.commit()

            # 创建后立即同步到运行中的调度器
            try:
                from scheduler import apply_monitor_schedule
                apply_monitor_schedule(schedule)
            except Exception as se:
                logger.warning(f"同步监控计划 #{schedule.id} 到调度器失败: {se}")

            log_audit(
                action='create',
                resource_type='monitor_schedule',
                resource_id=schedule.id,
                message=f'创建监控调度: {schedule.name}',
                user_id=current_user.id
            )

            flash('监控调度创建成功', 'success')
            return redirect(url_for('monitor_settings.schedule_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'创建监控调度失败: {str(e)}', 'danger')
    
    # 获取所有设备用于选择
    devices = Device.query.order_by(Device.name).all()
    
    return render_template('monitoring/schedule_form.html',
                         schedule=None,
                         devices=devices,
                         is_edit=False)

@monitoring_bp.route('/schedules/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def edit_schedule(schedule_id):
    """编辑监控调度"""
    schedule = MonitorSchedule.query.get_or_404(schedule_id)
    
    if request.method == 'POST':
        try:
            data = request.form
            
            schedule.name = data.get('name')
            schedule.description = data.get('description')
            schedule.monitor_type = data.get('monitor_type')
            schedule.target_type = data.get('target_type')
            schedule.schedule_type = data.get('schedule_type')
            schedule.enabled = data.get('enabled', 'off') == 'on'
            
            # 设置目标值
            target_value = data.get('target_value')
            if target_value:
                schedule.target_value = target_value
            
            # 设置调度参数
            if schedule.schedule_type == 'interval':
                interval = data.get('interval_seconds')
                if interval:
                    schedule.interval_seconds = int(interval)
            elif schedule.schedule_type == 'cron':
                cron_expr = data.get('cron_expression')
                if cron_expr:
                    schedule.cron_expression = cron_expr
            
            # 设置时间窗口
            start_time = data.get('start_time')
            end_time = data.get('end_time')
            weekdays = data.get('weekdays')
            
            if start_time:
                schedule.start_time = datetime.strptime(start_time, '%H:%M').time()
            else:
                schedule.start_time = None
                
            if end_time:
                schedule.end_time = datetime.strptime(end_time, '%H:%M').time()
            else:
                schedule.end_time = None
                
            schedule.weekdays = weekdays if weekdays else None
            
            # 设置配置
            config_data = {}
            for key in request.form:
                if key.startswith('config_'):
                    config_key = key[7:]  # 去掉'config_'前缀
                    config_data[config_key] = request.form[key]
            
            schedule.set_config(config_data)

            db.session.commit()

            # 保存后立即同步到运行中的调度器（启用则注册/更新，禁用则移除）
            try:
                from scheduler import apply_monitor_schedule
                apply_monitor_schedule(schedule)
            except Exception as se:
                logger.warning(f"同步监控计划 #{schedule.id} 到调度器失败: {se}")

            log_audit(
                action='update',
                resource_type='monitor_schedule',
                resource_id=schedule.id,
                message=f'更新监控调度: {schedule.name}',
                user_id=current_user.id
            )

            flash('监控调度更新成功', 'success')
            return redirect(url_for('monitor_settings.schedule_list'))

        except Exception as e:
            db.session.rollback()
            flash(f'更新监控调度失败: {str(e)}', 'danger')

    # 获取所有设备用于选择
    devices = Device.query.order_by(Device.name).all()

    return render_template('monitoring/schedule_form.html',
                         schedule=schedule,
                         devices=devices,
                         is_edit=True)


# ========== 通知配置编辑 ==========
@monitoring_bp.route('/notifications/<int:notification_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def notification_edit(notification_id):
    """编辑通知配置"""
    from flask import flash, redirect, url_for, request, render_template
    from app import db
    import json

    notification = NotificationConfig.query.get_or_404(notification_id)

    if request.method == 'POST':
        # 获取表单数据
        name = request.form.get('name')
        description = request.form.get('description')
        notification_type = request.form.get('notification_type')
        receivers_raw = request.form.get('receivers', '')
        receivers = [r.strip() for r in receivers_raw.split('\n') if r.strip()]
        trigger_on = request.form.get('trigger_on', 'all')
        trigger_delay = request.form.get('trigger_delay', 0, type=int)
        max_notifications = request.form.get('max_notifications', 10, type=int)
        title_template = request.form.get('title_template')
        message_template = request.form.get('message_template')
        config_raw = request.form.get('config', '{}')
        enabled = request.form.get('enabled') == 'on'

        # 验证必填字段
        if not name or not notification_type:
            flash('名称和通知类型为必填项', 'danger')
            return render_template('monitoring/notification_form.html', notification=notification, is_edit=True)

        # 解析配置 JSON
        try:
            config = json.loads(config_raw) if config_raw else {}
        except json.JSONDecodeError:
            config = {}
            flash('配置 JSON 格式错误', 'danger')
            return render_template('monitoring/notification_form.html', notification=notification, is_edit=True)

        # 更新对象
        notification.name = name
        notification.description = description
        notification.notification_type = notification_type
        notification.trigger_on = trigger_on
        notification.trigger_delay = trigger_delay
        notification.max_notifications = max_notifications
        notification.title_template = title_template
        notification.message_template = message_template
        notification.enabled = enabled
        notification.updated_by = current_user.username if current_user.is_authenticated else 'system'

        # 设置接收者列表和配置
        notification.set_receivers(receivers)
        notification.set_config(config)

        try:
            db.session.commit()
            log_audit(
                action='update',
                resource_type='notification_config',
                resource_id=notification.id,
                message=f'更新通知配置: {name}',
                user_id=current_user.id
            )
            flash(f'通知配置 "{name}" 更新成功', 'success')
            return redirect(url_for('monitoring.notification_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')

    # GET 请求显示表单
    return render_template('monitoring/notification_form.html', notification=notification, is_edit=True)


# ========== 通知配置测试 ==========
@monitoring_bp.route('/notifications/<int:notification_id>/test')
@login_required
@permission_required('monitor:view')
def notification_test(notification_id):
    """测试发送通知"""
    from flask import flash, redirect, url_for
    from app import db
    from datetime import datetime, timezone
    import json

    notification = NotificationConfig.query.get_or_404(notification_id)

    # 根据通知类型和配置发送测试消息
    try:
        # 调用实际的发送函数，这里用伪代码表示，需要根据您的通知渠道实现
        success, message = send_test_notification(notification)
        
        # 更新测试状态
        notification.test_status = 'success' if success else 'failed'
        notification.test_message = message
        notification.last_tested = datetime.now(timezone.utc)

        db.session.commit()

        log_audit(
            action='execute',
            resource_type='notification_config',
            resource_id=notification_id,
            message=f'测试通知: {notification.name}',
            user_id=current_user.id
        )

        if success:
            flash(f'测试通知发送成功: {message}', 'success')
        else:
            flash(f'测试通知发送失败: {message}', 'danger')
            
    except Exception as e:
        notification.test_status = 'failed'
        notification.test_message = str(e)
        notification.last_tested = datetime.now(timezone.utc)
        db.session.commit()
        flash(f'测试通知发送异常: {str(e)}', 'danger')

    return redirect(url_for('monitoring.notification_list'))

@monitoring_bp.route('/schedules/<int:schedule_id>/delete', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def delete_schedule(schedule_id):
    """删除监控调度"""
    try:
        schedule = MonitorSchedule.query.get_or_404(schedule_id)

        # 删除前先移除运行中的调度任务
        try:
            from scheduler import remove_monitor_schedule
            remove_monitor_schedule(schedule_id)
        except Exception as se:
            logger.warning(f"移除监控计划 #{schedule_id} 调度失败: {se}")

        db.session.delete(schedule)
        db.session.commit()

        log_audit(
            action='delete',
            resource_type='monitor_schedule',
            resource_id=schedule_id,
            message=f'删除监控调度',
            user_id=current_user.id
        )

        flash('监控调度删除成功', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'删除监控调度失败: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.schedule_list'))

@monitoring_bp.route('/schedules/<int:schedule_id>/toggle', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def toggle_schedule(schedule_id):
    """启用/禁用监控调度"""
    try:
        schedule = MonitorSchedule.query.get_or_404(schedule_id)
        schedule.enabled = not schedule.enabled

        db.session.commit()

        # 启用/禁用后立即同步到运行中的调度器
        try:
            from scheduler import apply_monitor_schedule
            apply_monitor_schedule(schedule)
        except Exception as se:
            logger.warning(f"同步监控计划 #{schedule.id} 到调度器失败: {se}")

        log_audit(
            action='update',
            resource_type='monitor_schedule',
            resource_id=schedule_id,
            message=f'{"启用" if schedule.enabled else "禁用"}监控调度',
            user_id=current_user.id
        )

        status = '启用' if schedule.enabled else '禁用'
        flash(f'监控调度已{status}', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'操作失败: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.schedule_list'))

@monitoring_bp.route('/schedules/<int:schedule_id>/run', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def run_schedule(schedule_id):
    """立即运行监控调度"""
    try:
        schedule = MonitorSchedule.query.get_or_404(schedule_id)

        # 立即触发对应的实际监控任务（后台线程执行，避免阻塞请求）
        from scheduler import run_monitor_schedule_now
        ok, msg = run_monitor_schedule_now(schedule)
        if not ok:
            flash(f'执行失败: {msg}', 'danger')
            return redirect(url_for('monitor_settings.schedule_list'))

        log_audit(
            action='execute',
            resource_type='monitor_schedule',
            resource_id=schedule_id,
            message=f'立即运行监控调度',
            user_id=current_user.id
        )

        flash('监控调度已开始执行', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'执行失败: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.schedule_list'))

# ========== 通知配置管理 ==========
@monitoring_bp.route('/notifications')
@login_required
@permission_required('monitor:view')
def notification_list():
    """通知配置列表"""
    notifications = NotificationConfig.query.order_by(NotificationConfig.name).all()
    
    return render_template('monitoring/notification_list.html',
                         notifications=notifications)

# ========== 通知配置创建 ==========
@monitoring_bp.route('/notifications/create', methods=['GET', 'POST'])

@login_required
@permission_required('monitor:edit')
def notification_create():
    """创建通知配置"""
    from flask import flash, redirect, url_for, request, render_template
    from app import db
    from datetime import datetime, timezone
    
    if request.method == 'POST':
        # 获取表单数据
        name = request.form.get('name')
        description = request.form.get('description')
        notification_type = request.form.get('notification_type')
        
        # 接收者处理
        receivers_raw = request.form.get('receivers', '')
        receivers = [r.strip() for r in receivers_raw.split('\n') if r.strip()]
        
        trigger_on = request.form.get('trigger_on', 'all')
        trigger_delay = request.form.get('trigger_delay', 0, type=int)
        max_notifications = request.form.get('max_notifications', 10, type=int)
        
        # 模板
        title_template = request.form.get('title_template')
        message_template = request.form.get('message_template')
        
        # 特定类型配置（JSON格式，简单起见只取一个字段）
        config_raw = request.form.get('config', '{}')
        try:
            config = json.loads(config_raw) if config_raw else {}
        except json.JSONDecodeError:
            config = {}
            flash('配置 JSON 格式错误', 'danger')
            return render_template('monitoring/notification_create.html')
        
        # 验证必填字段
        if not name or not notification_type:
            flash('名称和通知类型为必填项', 'danger')
            return render_template('monitoring/notification_create.html')
        
        # 创建新配置
        new_config = NotificationConfig(
            name=name,
            description=description,
            notification_type=notification_type,
            trigger_on=trigger_on,
            trigger_delay=trigger_delay,
            max_notifications=max_notifications,
            title_template=title_template,
            message_template=message_template,
            enabled=request.form.get('enabled') == 'on',  # 复选框
            created_by=current_user.username if current_user.is_authenticated else 'system'
        )
        # 设置接收者列表和配置
        new_config.set_receivers(receivers)
        new_config.set_config(config)
        
        try:
            db.session.add(new_config)
            db.session.commit()
            log_audit(
                action='create',
                resource_type='notification_config',
                resource_id=new_config.id,
                message=f'创建通知配置: {name}',
                user_id=current_user.id
            )
            flash(f'通知配置 "{name}" 创建成功', 'success')
            return redirect(url_for('monitoring.notification_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {str(e)}', 'danger')

    # GET 请求显示表单
    return render_template('monitoring/notification_create.html')

@monitoring_bp.route('/create/notifications/', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def create_notification():
    """创建通知配置"""
    if request.method == 'POST':
        try:
            data = request.form
            
            notification = NotificationConfig(
                name=data.get('name'),
                description=data.get('description'),
                notification_type=data.get('notification_type'),
                trigger_on=data.get('trigger_on', 'all'),
                enabled=data.get('enabled', 'off') == 'on',
                created_by=current_user.username
            )
            
            # 设置接收者
            receivers = data.get('receivers', '')
            if receivers:
                receiver_list = [r.strip() for r in receivers.split(',') if r.strip()]
                notification.set_receivers(receiver_list)
            
            # 设置内容模板
            notification.title_template = data.get('title_template', '')
            notification.message_template = data.get('message_template', '')
            
            # 设置特定类型配置
            config_data = {}
            for key in request.form:
                if key.startswith('config_'):
                    config_key = key[7:]  # 去掉'config_'前缀
                    config_data[config_key] = request.form[key]
            
            notification.set_config(config_data)
            
            db.session.add(notification)
            db.session.commit()

            log_audit(
                action='create',
                resource_type='notification_config',
                resource_id=notification.id,
                message=f'创建通知配置: {notification.name}',
                user_id=current_user.id
            )

            flash('通知配置创建成功', 'success')
            return redirect(url_for('monitor_settings.notification_list'))

        except Exception as e:
            db.session.rollback()
            flash(f'创建通知配置失败: {str(e)}', 'danger')

    return render_template('monitoring/notification_form.html',
                         notification=None,
                         is_edit=False)

# ========== 监控调度创建 ==========
@monitoring_bp.route('/schedules/create', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def schedule_create():
    """创建监控调度"""
    from flask import flash, redirect, url_for, request, render_template
    from app import db
    from datetime import datetime, time

    if request.method == 'POST':
        # 获取表单数据
        name = request.form.get('name')
        description = request.form.get('description')
        monitor_type = request.form.get('monitor_type')
        target_type = request.form.get('target_type')
        
        # target_value 和 config 为 JSON 文本，直接存储
        target_value = request.form.get('target_value', '{}')
        config = request.form.get('config', '{}')
        
        schedule_type = request.form.get('schedule_type')
        interval_seconds = request.form.get('interval_seconds', 60, type=int)
        cron_expression = request.form.get('cron_expression')
        
        # 时间窗口（可选）
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')
        weekdays = request.form.get('weekdays')
        
        enabled = request.form.get('enabled') == 'on'
        
        # 验证必填字段
        if not name or not monitor_type or not target_type or not schedule_type:
            flash('请填写所有必填字段', 'danger')
            return render_template('monitoring/schedule_create.html')
        
        # 创建调度对象
        schedule = MonitorSchedule(
            name=name,
            description=description,
            monitor_type=monitor_type,
            target_type=target_type,
            target_value=target_value,  # 直接存储 JSON 字符串
            schedule_type=schedule_type,
            interval_seconds=interval_seconds if schedule_type == 'interval' else None,
            cron_expression=cron_expression if schedule_type == 'cron' else None,
            weekdays=weekdays,
            enabled=enabled,
            created_by=current_user.username if current_user.is_authenticated else 'system'
        )
        
        # 处理时间字段
        if start_time_str:
            try:
                schedule.start_time = datetime.strptime(start_time_str, '%H:%M').time()
            except ValueError:
                flash('开始时间格式错误，请使用 HH:MM 格式', 'danger')
                return render_template('monitoring/schedule_create.html')
        if end_time_str:
            try:
                schedule.end_time = datetime.strptime(end_time_str, '%H:%M').time()
            except ValueError:
                flash('结束时间格式错误，请使用 HH:MM 格式', 'danger')
                return render_template('monitoring/schedule_create.html')
        
        # 设置配置（JSON）
        schedule.set_config(json.loads(config) if config else {})
        
        # 计算下次运行时间（可选，可留空由调度器计算）
        schedule.next_run = None
        
        try:
            db.session.add(schedule)
            db.session.commit()

            log_audit(
                action='create',
                resource_type='monitor_schedule',
                resource_id=schedule.id,
                message=f'创建监控调度: {name}',
                user_id=current_user.id
            )

            flash(f'监控调度 "{name}" 创建成功', 'success')
            return redirect(url_for('monitoring.schedule_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {str(e)}', 'danger')

    # GET 请求显示表单
    return render_template('monitoring/schedule_create.html')


@monitoring_bp.route('/notifications/<int:notification_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def edit_notification(notification_id):
    """编辑通知配置"""
    notification = NotificationConfig.query.get_or_404(notification_id)
    
    if request.method == 'POST':
        try:
            data = request.form
            
            notification.name = data.get('name')
            notification.description = data.get('description')
            notification.notification_type = data.get('notification_type')
            notification.trigger_on = data.get('trigger_on', 'all')
            notification.enabled = data.get('enabled', 'off') == 'on'
            
            # 设置接收者
            receivers = data.get('receivers', '')
            if receivers:
                receiver_list = [r.strip() for r in receivers.split(',') if r.strip()]
                notification.set_receivers(receiver_list)
            else:
                notification.set_receivers([])
            
            # 设置内容模板
            notification.title_template = data.get('title_template', '')
            notification.message_template = data.get('message_template', '')
            
            # 设置特定类型配置
            config_data = {}
            for key in request.form:
                if key.startswith('config_'):
                    config_key = key[7:]  # 去掉'config_'前缀
                    config_data[config_key] = request.form[key]
            
            notification.set_config(config_data)

            db.session.commit()

            log_audit(
                action='update',
                resource_type='notification_config',
                resource_id=notification.id,
                message=f'更新通知配置: {notification.name}',
                user_id=current_user.id
            )

            flash('通知配置更新成功', 'success')
            return redirect(url_for('monitor_settings.notification_list'))

        except Exception as e:
            db.session.rollback()
            flash(f'更新通知配置失败: {str(e)}', 'danger')

    return render_template('monitoring/notification_form.html',
                         notification=notification,
                         is_edit=True)

@monitoring_bp.route('/notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def delete_notification(notification_id):
    """删除通知配置"""
    try:
        notification = NotificationConfig.query.get_or_404(notification_id)
        
        db.session.delete(notification)
        db.session.commit()

        log_audit(
            action='delete',
            resource_type='notification_config',
            resource_id=notification_id,
            message=f'删除通知配置: {notification.name}',
            user_id=current_user.id
        )

        flash('通知配置删除成功', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'删除通知配置失败: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.notification_list'))

@monitoring_bp.route('/notifications/<int:notification_id>/test', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def test_notification(notification_id):
    """测试通知配置"""
    try:
        notification = NotificationConfig.query.get_or_404(notification_id)

        from services.notification_service import send_notification
        success, message = send_notification(notification)

        notification.last_tested = datetime.now(timezone.utc)
        notification.test_status = 'success' if success else 'failed'
        notification.test_message = message

        db.session.commit()

        log_audit(
            action='execute',
            resource_type='notification_config',
            resource_id=notification_id,
            message=f'测试通知配置: {notification.name}',
            user_id=current_user.id
        )

        if success:
            flash(f'测试通知发送成功: {message}', 'success')
        else:
            flash(f'测试通知发送失败: {message}', 'danger')

    except Exception as e:
        db.session.rollback()
        flash(f'测试通知异常: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.notification_list'))

# ========== 设备监控配置 ==========
@monitoring_bp.route('/device_configs')
@login_required
@permission_required('monitor:view')
def device_config_list():
    """设备监控配置列表"""
    # 获取查询参数
    device_name = request.args.get('device_name', '')
    device_type = request.args.get('device_type', '')
    enabled = request.args.get('enabled', '')
    
    # 构建查询
    query = DeviceMonitorConfig.query.join(Device)
    
    if device_name:
        query = query.filter(Device.name.ilike(f'%{device_name}%'))
    
    if device_type:
        query = query.filter(Device.device_type == device_type)
    
    if enabled == 'true':
        query = query.filter(DeviceMonitorConfig.enabled == True)
    elif enabled == 'false':
        query = query.filter(DeviceMonitorConfig.enabled == False)
    
    configs = query.order_by(Device.name).all()
    
    # 获取设备类型列表
    device_types = db.session.query(Device.device_type).distinct().all()
    
    return render_template('monitoring/device_config_list.html',
                         configs=configs,
                         device_types=[t[0] for t in device_types],
                         device_name=device_name,
                         device_type=device_type,
                         enabled=enabled)
# ========== 设备监控配置详情 ==========
@monitoring_bp.route('/device_configs/<int:config_id>')
@login_required
@permission_required('monitor:view')
def device_config_view(config_id):
    """查看设备监控配置详情"""
    from flask import render_template
    config = DeviceMonitorConfig.query.get_or_404(config_id)
    
    return render_template('monitoring/device_config_view.html', config=config)

# ========== 设备监控配置编辑 ==========
@monitoring_bp.route('/device_configs/<int:config_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def device_config_edit(config_id):
    """编辑设备监控配置"""
    from flask import flash, redirect, url_for, request, render_template
    from app import db
    from datetime import datetime, timezone
    import json

    config = DeviceMonitorConfig.query.get_or_404(config_id)
    # 获取所有设备（用于展示设备列表，但编辑时通常不允许更换设备，我们可仅传递当前设备或全部设备）
    devices = Device.query.order_by(Device.name).all()

    if request.method == 'POST':
        # 获取表单数据（注意：设备 ID 可能不在表单中，我们保留原设备 ID）
        enable_ping = request.form.get('enable_ping') == 'on'
        enable_snmp = request.form.get('enable_snmp') == 'on'
        enable_ssh = request.form.get('enable_ssh')  # auto, yes, no
        enable_api = request.form.get('enable_api') == 'on'

        ping_interval = request.form.get('ping_interval', 60, type=int)
        snmp_interval = request.form.get('snmp_interval', 300, type=int)
        ssh_interval = request.form.get('ssh_interval', 300, type=int)
        api_interval = request.form.get('api_interval', 300, type=int)

        ping_timeout = request.form.get('ping_timeout', 2.0, type=float)
        snmp_timeout = request.form.get('snmp_timeout', 5.0, type=float)
        ssh_timeout = request.form.get('ssh_timeout', 10.0, type=float)
        api_timeout = request.form.get('api_timeout', 5.0, type=float)

        retry_count = request.form.get('retry_count', 3, type=int)
        retry_interval = request.form.get('retry_interval', 5, type=int)

        # SNMP配置
        snmp_version = request.form.get('snmp_version', 2, type=int)
        snmp_community = request.form.get('snmp_community')
        snmp_username = request.form.get('snmp_username')
        snmp_auth_password = request.form.get('snmp_auth_password')
        snmp_priv_password = request.form.get('snmp_priv_password')
        snmp_auth_protocol = request.form.get('snmp_auth_protocol')
        snmp_priv_protocol = request.form.get('snmp_priv_protocol')

        # SSH配置
        ssh_username = request.form.get('ssh_username')
        ssh_password = request.form.get('ssh_password')
        ssh_key_file = request.form.get('ssh_key_file')
        ssh_port = request.form.get('ssh_port', 22, type=int)

        # API配置
        api_url = request.form.get('api_url')
        api_method = request.form.get('api_method', 'GET')
        api_headers_raw = request.form.get('api_headers', '{}')
        api_body_raw = request.form.get('api_body', '{}')
        api_auth_type = request.form.get('api_auth_type')
        api_auth_value = request.form.get('api_auth_value')

        monitor_metrics_raw = request.form.get('monitor_metrics', '{}')
        inherit_alerts = request.form.get('inherit_alerts') == 'on'
        enabled = request.form.get('enabled') == 'on'

        # 解析 JSON 字段
        try:
            api_headers = json.loads(api_headers_raw) if api_headers_raw else {}
            api_body = json.loads(api_body_raw) if api_body_raw else {}
            monitor_metrics = json.loads(monitor_metrics_raw) if monitor_metrics_raw else {}
        except json.JSONDecodeError as e:
            flash(f'JSON 格式错误: {str(e)}', 'danger')
            return render_template('monitoring/device_config_edit.html', config=config, devices=devices)

        # 更新配置对象
        config.enable_ping = enable_ping
        config.enable_snmp = enable_snmp
        config.enable_ssh = enable_ssh
        config.enable_api = enable_api
        config.ping_interval = ping_interval
        config.snmp_interval = snmp_interval
        config.ssh_interval = ssh_interval
        config.api_interval = api_interval
        config.ping_timeout = ping_timeout
        config.snmp_timeout = snmp_timeout
        config.ssh_timeout = ssh_timeout
        config.api_timeout = api_timeout
        config.retry_count = retry_count
        config.retry_interval = retry_interval
        config.snmp_version = snmp_version
        config.snmp_community = snmp_community
        config.snmp_username = snmp_username
        config.snmp_auth_protocol = snmp_auth_protocol
        config.snmp_priv_protocol = snmp_priv_protocol
        config.ssh_username = ssh_username
        config.ssh_port = ssh_port
        config.ssh_key_file = ssh_key_file
        config.api_url = api_url
        config.api_method = api_method
        config.api_auth_type = api_auth_type
        config.api_auth_value = api_auth_value
        config.inherit_alerts = inherit_alerts
        config.enabled = enabled
        config.updated_by = current_user.username if current_user.is_authenticated else 'system'

        # 更新密码字段（仅当表单中提供了新密码时才更新）
        if snmp_auth_password:
            config.snmp_auth_password = snmp_auth_password
        if snmp_priv_password:
            config.snmp_priv_password = snmp_priv_password
        if ssh_password:
            config.ssh_password = ssh_password

        # 设置 JSON 字段
        config.set_api_headers(api_headers)
        config.set_monitor_metrics(monitor_metrics)
        config.api_body = api_body_raw  # 直接存原始字符串

        try:
            db.session.commit()
            log_audit(
                action='update',
                resource_type='device_monitor_config',
                resource_id=config_id,
                message=f'编辑设备监控配置',
                user_id=current_user.id
            )
            flash(f'设备监控配置更新成功', 'success')
            return redirect(url_for('monitoring.device_config_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')

    # GET 请求显示表单
    return render_template('monitoring/device_config_edit.html', config=config, devices=devices)

# ========== 设备监控配置启用/禁用切换 ==========
@monitoring_bp.route('/device_configs/<int:config_id>/toggle')
@login_required
@permission_required('monitor:view')
def device_config_toggle(config_id):
    """切换设备监控配置的启用状态"""
    from flask import flash, redirect, url_for
    from app import db
    from datetime import datetime, timezone

    config = DeviceMonitorConfig.query.get_or_404(config_id)
    
    # 切换启用状态
    config.enabled = not config.enabled
    config.updated_at = datetime.now(timezone.utc)
    
    try:
        db.session.commit()
        status = "启用" if config.enabled else "禁用"
        # 修复 f-string 语法错误：外层使用双引号，内层使用单引号
        flash(f"设备 '{config.device.name if config.device else '未知'}' 的监控配置已{status}", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'切换状态失败: {str(e)}', 'danger')
    
    return redirect(url_for('monitoring.device_config_list'))

# ========== 设备监控配置删除 ==========
@monitoring_bp.route('/device_config/<int:config_id>/delete')
@login_required
@permission_required('monitor:view')
#@admin_required
def device_config_delete(config_id):
    """删除监控配置"""
    config = DeviceConfig.query.get_or_404(config_id)
    device_name = config.device.name if config.device else '未知'
    db.session.delete(config)
    db.session.commit()
    flash(f'已删除设备 {device_name} 的监控配置', 'success')
    return redirect(url_for('monitoring.device_config_list'))

# ========== 设备监控配置创建 ==========
@monitoring_bp.route('/device_configs/create', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def device_config_create():
    """创建设备监控配置"""
    from flask import flash, redirect, url_for, request, render_template
    from app import db
    from datetime import datetime, timezone
    import json

    # 获取所有设备用于选择（只展示未配置监控的设备，或全部？这里展示全部，由后端校验唯一性）
    devices = Device.query.order_by(Device.name).all()

    if request.method == 'POST':
        # 获取表单数据
        device_id = request.form.get('device_id', type=int)
        enable_ping = request.form.get('enable_ping') == 'on'
        enable_snmp = request.form.get('enable_snmp') == 'on'
        enable_ssh = request.form.get('enable_ssh')  # auto, yes, no
        enable_api = request.form.get('enable_api') == 'on'

        ping_interval = request.form.get('ping_interval', 60, type=int)
        snmp_interval = request.form.get('snmp_interval', 300, type=int)
        ssh_interval = request.form.get('ssh_interval', 300, type=int)
        api_interval = request.form.get('api_interval', 300, type=int)

        ping_timeout = request.form.get('ping_timeout', 2.0, type=float)
        snmp_timeout = request.form.get('snmp_timeout', 5.0, type=float)
        ssh_timeout = request.form.get('ssh_timeout', 10.0, type=float)
        api_timeout = request.form.get('api_timeout', 5.0, type=float)

        retry_count = request.form.get('retry_count', 3, type=int)
        retry_interval = request.form.get('retry_interval', 5, type=int)

        # SNMP配置
        snmp_version = request.form.get('snmp_version', 2, type=int)
        snmp_community = request.form.get('snmp_community')
        snmp_username = request.form.get('snmp_username')
        snmp_auth_password = request.form.get('snmp_auth_password')
        snmp_priv_password = request.form.get('snmp_priv_password')
        snmp_auth_protocol = request.form.get('snmp_auth_protocol')
        snmp_priv_protocol = request.form.get('snmp_priv_protocol')

        # SSH配置
        ssh_username = request.form.get('ssh_username')
        ssh_password = request.form.get('ssh_password')
        ssh_key_file = request.form.get('ssh_key_file')
        ssh_port = request.form.get('ssh_port', 22, type=int)

        # API配置
        api_url = request.form.get('api_url')
        api_method = request.form.get('api_method', 'GET')
        api_headers_raw = request.form.get('api_headers', '{}')
        api_body_raw = request.form.get('api_body', '{}')
        api_auth_type = request.form.get('api_auth_type')
        api_auth_value = request.form.get('api_auth_value')

        # 监控指标配置（JSON）
        monitor_metrics_raw = request.form.get('monitor_metrics', '{}')
        inherit_alerts = request.form.get('inherit_alerts') == 'on'
        enabled = request.form.get('enabled') == 'on'

        # 验证必填字段
        if not device_id:
            flash('必须选择设备', 'danger')
            return render_template('monitoring/device_config_create.html', devices=devices)

        # 检查该设备是否已有监控配置
        existing = DeviceMonitorConfig.query.filter_by(device_id=device_id).first()
        if existing:
            flash('该设备已存在监控配置，请勿重复创建', 'danger')
            return render_template('monitoring/device_config_create.html', devices=devices)

        # 解析 JSON 字段
        try:
            api_headers = json.loads(api_headers_raw) if api_headers_raw else {}
            api_body = json.loads(api_body_raw) if api_body_raw else {}
            monitor_metrics = json.loads(monitor_metrics_raw) if monitor_metrics_raw else {}
        except json.JSONDecodeError as e:
            flash(f'JSON 格式错误: {str(e)}', 'danger')
            return render_template('monitoring/device_config_create.html', devices=devices)

        # 创建新配置
        config = DeviceMonitorConfig(
            device_id=device_id,
            enable_ping=enable_ping,
            enable_snmp=enable_snmp,
            enable_ssh=enable_ssh,
            enable_api=enable_api,
            ping_interval=ping_interval,
            snmp_interval=snmp_interval,
            ssh_interval=ssh_interval,
            api_interval=api_interval,
            ping_timeout=ping_timeout,
            snmp_timeout=snmp_timeout,
            ssh_timeout=ssh_timeout,
            api_timeout=api_timeout,
            retry_count=retry_count,
            retry_interval=retry_interval,
            snmp_version=snmp_version,
            snmp_community=snmp_community,
            snmp_username=snmp_username,
            snmp_auth_password=snmp_auth_password,
            snmp_priv_password=snmp_priv_password,
            snmp_auth_protocol=snmp_auth_protocol,
            snmp_priv_protocol=snmp_priv_protocol,
            ssh_username=ssh_username,
            ssh_password=ssh_password,
            ssh_key_file=ssh_key_file,
            ssh_port=ssh_port,
            api_url=api_url,
            api_method=api_method,
            api_auth_type=api_auth_type,
            api_auth_value=api_auth_value,
            inherit_alerts=inherit_alerts,
            enabled=enabled,
            created_by=current_user.username if current_user.is_authenticated else 'system'
        )
        # 设置 JSON 字段
        config.set_api_headers(api_headers)
        config.set_monitor_metrics(monitor_metrics)
        # api_body 不是模型字段？模型中只有 api_headers 和 monitor_metrics，但有个 api_body 字段？检查模型：模型中确实有 api_body 字段 (db.Column(db.Text))，需要设置
        config.api_body = api_body_raw  # 直接存字符串？但模型中定义为 Text，可以存 JSON 字符串，这里存原始字符串，解析由使用者负责。也可以像 headers 一样有 set/get，但未定义。简单起见直接存字符串。
        # 注意：模型中没有 api_body 的 setter，我们直接赋值

        try:
            db.session.add(config)
            db.session.commit()
            log_audit(
                action='create',
                resource_type='device_monitor_config',
                resource_id=config.id,
                message='创建设备监控配置',
                details={'device_id': device_id},
                user_id=current_user.id
            )
            flash(f'设备监控配置创建成功', 'success')
            return redirect(url_for('monitoring.device_config_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {str(e)}', 'danger')

    # GET 请求显示表单
    return render_template('monitoring/device_config_create.html', devices=devices)
@monitoring_bp.route('/device_configs/<int:device_id>')
@login_required
@permission_required('monitor:view')
def device_config_detail(device_id):
    """设备监控配置详情"""
    device = Device.query.get_or_404(device_id)
    
    # 获取或创建配置
    config = DeviceMonitorConfig.query.filter_by(device_id=device_id).first()
    
    if not config:
        # 创建默认配置
        config = DeviceMonitorConfig(
            device_id=device_id,
            enable_ping=True,
            enable_snmp=device.snmp_community is not None,
            enable_ssh='auto',
            enable_api=False,
            ping_interval=60,
            snmp_interval=300,
            ssh_interval=300,
            api_interval=300,
            ping_timeout=2.0,
            snmp_timeout=5.0,
            ssh_timeout=10.0,
            api_timeout=5.0,
            retry_count=3,
            retry_interval=5,
            snmp_version=device.snmp_version or 2,
            snmp_community=device.snmp_community,
            ssh_username=device.ssh_username,
            ssh_password=device.ssh_password,
            ssh_port=22,
            enabled=True,
            created_by=current_user.username
        )
        
        db.session.add(config)
        db.session.commit()
    
    return render_template('monitoring/device_config_detail.html',
                         config=config,
                         device=device)

@monitoring_bp.route('/device_configs/<int:device_id>/save', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def save_device_config(device_id):
    """保存设备监控配置"""
    try:
        device = Device.query.get_or_404(device_id)
        config = DeviceMonitorConfig.query.filter_by(device_id=device_id).first()
        
        if not config:
            config = DeviceMonitorConfig(
                device_id=device_id,
                created_by=current_user.username
            )
            db.session.add(config)
        
        data = request.form
        
        # 更新基本设置
        config.enable_ping = data.get('enable_ping', 'off') == 'on'
        config.enable_snmp = data.get('enable_snmp', 'off') == 'on'
        config.enable_ssh = data.get('enable_ssh', 'auto')
        config.enable_api = data.get('enable_api', 'off') == 'on'
        
        config.ping_interval = int(data.get('ping_interval', 60))
        config.snmp_interval = int(data.get('snmp_interval', 300))
        config.ssh_interval = int(data.get('ssh_interval', 300))
        config.api_interval = int(data.get('api_interval', 300))
        
        config.ping_timeout = float(data.get('ping_timeout', 2.0))
        config.snmp_timeout = float(data.get('snmp_timeout', 5.0))
        config.ssh_timeout = float(data.get('ssh_timeout', 10.0))
        config.api_timeout = float(data.get('api_timeout', 5.0))
        
        config.retry_count = int(data.get('retry_count', 3))
        config.retry_interval = int(data.get('retry_interval', 5))
        
        # 更新SNMP配置
        config.snmp_version = int(data.get('snmp_version', 2))
        config.snmp_community = data.get('snmp_community')
        
        # 更新SSH配置
        config.ssh_username = data.get('ssh_username')
        config.ssh_password = data.get('ssh_password')
        config.ssh_port = int(data.get('ssh_port', 22))
        
        # 更新API配置
        config.api_url = data.get('api_url')
        config.api_method = data.get('api_method', 'GET')
        
        # 更新设备表中的相应字段
        device.snmp_version = config.snmp_version
        device.snmp_community = config.snmp_community
        device.ssh_username = config.ssh_username
        device.ssh_password = config.ssh_password
        
        config.enabled = data.get('enabled', 'off') == 'on'
        config.updated_at = datetime.now(timezone.utc)

        db.session.commit()

        log_audit(
            action='update',
            resource_type='device_monitor_config',
            resource_id=device_id,
            message=f'保存设备监控配置: 设备ID={device_id}',
            user_id=current_user.id
        )

        flash('设备监控配置保存成功', 'success')
        return redirect(url_for('monitor_settings.device_config_detail', device_id=device_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'保存配置失败: {str(e)}', 'danger')
        return redirect(url_for('monitor_settings.device_config_detail', device_id=device_id))

@monitoring_bp.route('/device_configs/<int:device_id>/toggle', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def toggle_device_config(device_id):
    """启用/禁用设备监控"""
    try:
        config = DeviceMonitorConfig.query.filter_by(device_id=device_id).first()
        
        if not config:
            flash('设备监控配置不存在', 'warning')
            return redirect(url_for('monitor_settings.device_config_list'))
        
        config.enabled = not config.enabled

        db.session.commit()

        log_audit(
            action='update',
            resource_type='device_monitor_config',
            resource_id=device_id,
            message=f'{"启用" if config.enabled else "禁用"}设备监控: 设备ID={device_id}',
            user_id=current_user.id
        )

        status = '启用' if config.enabled else '禁用'
        flash(f'设备监控已{status}', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'操作失败: {str(e)}', 'danger')
    
    return redirect(url_for('monitor_settings.device_config_list'))

@monitoring_bp.route('/device_configs/batch_update', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def batch_update_device_configs():
    """批量更新设备监控配置"""
    try:
        data = request.get_json()
        device_ids = data.get('device_ids', [])
        updates = data.get('updates', {})
        
        for device_id in device_ids:
            config = DeviceMonitorConfig.query.filter_by(device_id=device_id).first()
            
            if not config:
                config = DeviceMonitorConfig(
                    device_id=device_id,
                    created_by=current_user.username
                )
                db.session.add(config)
            
            # 应用更新
            for key, value in updates.items():
                if hasattr(config, key):
                    # 处理不同类型的值
                    if isinstance(getattr(config, key), bool):
                        setattr(config, key, str(value).lower() in ('true', '1', 'yes'))
                    elif isinstance(getattr(config, key), int):
                        setattr(config, key, int(value))
                    elif isinstance(getattr(config, key), float):
                        setattr(config, key, float(value))
                    else:
                        setattr(config, key, value)
            
            config.updated_at = datetime.now(timezone.utc)
        
        db.session.commit()

        log_audit(
            action='update',
            resource_type='device_monitor_config',
            resource_id='batch',
            message=f'批量更新 {len(device_ids)} 个设备的监控配置',
            details={'device_ids': device_ids},
            user_id=current_user.id
        )

        return jsonify({
            'success': True,
            'message': f'已更新 {len(device_ids)} 个设备的监控配置'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'批量更新失败: {str(e)}'
        }), 500

# ========== API接口 ==========
@monitoring_bp.route('/api/settings')
@login_required
@permission_required('monitor:view')
def api_get_settings():
    """获取监控设置API"""
    category = request.args.get('category', 'general')
    scope = request.args.get('scope', 'global')
    target_id = request.args.get('target_id', type=int)
    
    query = MonitorSetting.query.filter_by(
        category=category,
        scope=scope,
        enabled=True
    )
    
    if target_id:
        query = query.filter_by(target_id=target_id)
    
    settings = query.all()
    
    result = {}
    for setting in settings:
        result[setting.setting_key] = setting.get_value()
    
    return jsonify(result)

@monitoring_bp.route('/api/settings/<string:key>', methods=['GET', 'PUT'])
@login_required
@permission_required('monitor:edit')
def api_setting_detail(key):
    """监控设置详情API"""
    scope = request.args.get('scope', 'global')
    target_id = request.args.get('target_id', type=int)
    
    if request.method == 'GET':
        setting = MonitorSetting.query.filter_by(
            setting_key=key,
            scope=scope
        ).first()
        
        if not setting:
            return jsonify({'error': '设置不存在'}), 404
        
        return jsonify(setting.to_dict())
    
    elif request.method == 'PUT':
        data = request.get_json()
        
        setting = MonitorSetting.query.filter_by(
            setting_key=key,
            scope=scope
        ).first()
        
        if not setting:
            # 创建新设置
            setting = MonitorSetting(
                setting_key=key,
                scope=scope,
                created_by=current_user.username
            )
            db.session.add(setting)
        
        if 'value' in data:
            setting.set_value(data['value'])
        
        if 'category' in data:
            setting.category = data['category']
        
        if 'description' in data:
            setting.description = data['description']
        
        if 'enabled' in data:
            setting.enabled = data['enabled']
        
        setting.updated_at = datetime.now(timezone.utc)
        setting.updated_by = current_user.username
        
        db.session.commit()

        log_audit(
            action='update',
            resource_type='monitor_setting',
            resource_id=key,
            message=f'更新监控设置: {key}',
            details={'scope': scope},
            user_id=current_user.id
        )

        return jsonify({
            'success': True,
            'message': '设置保存成功',
            'setting': setting.to_dict()
        })

@monitoring_bp.route('/api/default_settings')
@login_required
@permission_required('monitor:view')
def api_default_settings():
    """获取默认监控设置"""
    # 定义默认设置
    default_settings = {
        'ping': {
            'enabled': True,
            'interval': 60,
            'timeout': 2.0,
            'retry_count': 3,
            'retry_interval': 5
        },
        'snmp': {
            'enabled': False,
            'interval': 300,
            'timeout': 5.0,
            'version': 2,
            'community': 'public'
        },
        'ssh': {
            'enabled': 'auto',
            'interval': 300,
            'timeout': 10.0,
            'port': 22
        },
        'alert': {
            'cpu_threshold': 90,
            'memory_threshold': 90,
            'disk_threshold': 90,
            'ping_threshold': 100,
            'retry_before_alert': 3
        },
        'notification': {
            'email_enabled': False,
            'sms_enabled': False,
            'webhook_enabled': False,
            'min_severity': 'warning'
        }
    }
    
    return jsonify(default_settings)

# 初始化默认设置
def init_default_settings():
    """初始化默认监控设置"""
    default_settings = [
        # Ping监控设置
        {
            'key': 'ping_enabled',
            'value': True,
            'type': 'boolean',
            'category': 'ping',
            'description': '是否启用Ping监控'
        },
        {
            'key': 'ping_interval',
            'value': 60,
            'type': 'number',
            'category': 'ping',
            'description': 'Ping监控间隔（秒）'
        },
        # SNMP监控设置
        {
            'key': 'snmp_default_community',
            'value': 'public',
            'type': 'string',
            'category': 'snmp',
            'description': 'SNMP默认团体名'
        },
        # 告警设置
        {
            'key': 'alert_cpu_threshold',
            'value': 90,
            'type': 'number',
            'category': 'alert',
            'description': 'CPU使用率告警阈值（%）'
        },
        {
            'key': 'alert_memory_threshold',
            'value': 90,
            'type': 'number',
            'category': 'alert',
            'description': '内存使用率告警阈值（%）'
        },
        # 通知设置
        {
            'key': 'notification_email_server',
            'value': '',
            'type': 'string',
            'category': 'notification',
            'description': '邮件服务器地址'
        },
        {
            'key': 'notification_email_port',
            'value': 587,
            'type': 'number',
            'category': 'notification',
            'description': '邮件服务器端口'
        },
    ]
    
    for setting_data in default_settings:
        setting = MonitorSetting.query.filter_by(
            setting_key=setting_data['key'],
            scope='global'
        ).first()
        
        if not setting:
            setting = MonitorSetting(
                setting_key=setting_data['key'],
                setting_type=setting_data['type'],
                category=setting_data['category'],
                scope='global',
                description=setting_data['description'],
                is_default=True,
                created_by='system'
            )
            setting.set_value(setting_data['value'])
            db.session.add(setting)
    
    try:
        db.session.commit()
    except:
        db.session.rollback()

#


# ========== 监控设置主页面 ==========
@monitoring_bp.route('/monitor_settings/')
@login_required
@permission_required('monitor:view')
def monitor_settings():
    """监控设置主页面"""
    try:
        # 从 monitoring_stats 导入所有需要的函数
        from utils.monitoring_stats import (
            get_global_settings,
            get_schedules,
            get_notifications,
            get_monitor_data_size,
            get_alert_rule_count,
            get_last_monitor_time,
            get_enabled_device_monitor_count,
            get_active_alert_count
        )
        
        # 获取所有数据
        global_settings = get_global_settings()
        schedules = get_schedules()
        notifications = get_notifications()
        
        # 获取统计信息
        monitor_data_size = get_monitor_data_size()
        alert_rule_count = get_alert_rule_count()
        last_monitor_time = get_last_monitor_time()
        enabled_device_monitor_count = get_enabled_device_monitor_count()
        active_alert_count = get_active_alert_count()
        
    except ImportError as e:
        current_app.logger.error(f"导入监控统计函数失败: {e}")
        # 如果导入失败，使用备用方案
        categories = db.session.query(MonitorSetting.category).distinct().all()
        
        global_settings = {}
        for category in categories:
            category_name = category[0]
            settings = MonitorSetting.query.filter_by(
                category=category_name, 
                scope='global',
                enabled=True
            ).all()
            if settings:
                global_settings[category_name] = settings
        
        schedules = MonitorSchedule.query.order_by(MonitorSchedule.name).all()
        notifications = NotificationConfig.query.order_by(NotificationConfig.name).all()
        
        # 设置默认统计值
        monitor_data_size = "统计中..."
        alert_rule_count = 0
        last_monitor_time = "无记录"
        enabled_device_monitor_count = 0
        active_alert_count = 0
    
    return render_template('monitoring/settings.html',
        global_settings=global_settings,
        schedules=schedules,
        notifications=notifications,
        monitor_data_size=monitor_data_size,
        alert_rule_count=alert_rule_count,
        last_monitor_time=last_monitor_time,
        enabled_device_monitor_count=enabled_device_monitor_count,
        active_alert_count=active_alert_count
    )

@monitoring_bp.route('/api/monitoring/status')
@login_required
@permission_required('monitor:view')
def api_monitoring_status():
    """获取监控状态"""
    try:
        # 获取所有设备
        devices = Device.query.all()
        
        # 统计状态
        device_count = len(devices)
        online_count = sum(1 for d in devices if d.status == 'online')
        offline_count = sum(1 for d in devices if d.status == 'offline')
        warning_count = sum(1 for d in devices if d.status == 'warning')
        
        # 获取连接状态
        connections = ConnectionPath.query.all()
        active_connections = sum(1 for c in connections if c.link_status == 'active')
        total_connections = len(connections)
        
        # 获取最近的性能指标
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_metrics = PerformanceMetric.query.filter(
            PerformanceMetric.timestamp >= recent_time
        ).order_by(PerformanceMetric.timestamp.desc()).limit(50).all()
        
        # 计算平均性能
        if recent_metrics:
            cpu_avg = sum(m.cpu_usage or 0 for m in recent_metrics) / len(recent_metrics)
            memory_avg = sum(m.memory_usage or 0 for m in recent_metrics) / len(recent_metrics)
            network_avg = sum(m.network_usage or 0 for m in recent_metrics) / len(recent_metrics)
        else:
            cpu_avg = memory_avg = network_avg = 0
        
        # 生成响应
        status_data = {
            'system_status': 'healthy' if offline_count == 0 else 'warning',
            'device_count': device_count,
            'online_devices': online_count,
            'offline_devices': offline_count,
            'warning_devices': warning_count,
            'connection_count': total_connections,
            'active_connections': active_connections,
            'connection_health': (active_connections / total_connections * 100) if total_connections > 0 else 100,
            'performance': {
                'cpu_usage': round(cpu_avg, 2),
                'memory_usage': round(memory_avg, 2),
                'network_usage': round(network_avg, 2),
            },
            'alerts': {
                'critical': random.randint(0, 2),
                'warning': random.randint(0, 5),
                'info': random.randint(0, 10),
            },
            'last_updated': datetime.now(timezone.utc).isoformat()
        }
        
        return jsonify(status_data)
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'system_status': 'error',
            'last_updated': datetime.now(timezone.utc).isoformat()
        }), 500

@monitoring_bp.route('/api/device/<int:device_id>/performance')
@login_required
@permission_required('monitor:view')
def api_device_performance(device_id):
    """获取设备性能数据"""
    try:
        device = Device.query.get_or_404(device_id)
        
        # 获取时间范围参数
        time_range = request.args.get('range', 'hour')  # hour, day, week, month
        now = datetime.now(timezone.utc)
        
        # 根据时间范围计算起始时间
        if time_range == 'hour':
            start_time = now - timedelta(hours=1)
        elif time_range == 'day':
            start_time = now - timedelta(days=1)
        elif time_range == 'week':
            start_time = now - timedelta(weeks=1)
        elif time_range == 'month':
            start_time = now - timedelta(days=30)
        else:
            start_time = now - timedelta(hours=1)
        
        # 查询性能指标
        metrics = PerformanceMetric.query.filter(
            PerformanceMetric.device_id == device_id,
            PerformanceMetric.timestamp >= start_time
        ).order_by(PerformanceMetric.timestamp.asc()).all()
        
        # 准备图表数据
        timestamps = [m.timestamp.isoformat() for m in metrics]
        cpu_usage = [m.cpu_usage or 0 for m in metrics]
        memory_usage = [m.memory_usage or 0 for m in metrics]
        network_usage = [m.network_usage or 0 for m in metrics]
        disk_usage = [m.disk_usage or 0 for m in metrics]
        
        return jsonify({
            'device_id': device_id,
            'device_name': device.name,
            'time_range': time_range,
            'timestamps': timestamps,
            'cpu_usage': cpu_usage,
            'memory_usage': memory_usage,
            'network_usage': network_usage,
            'disk_usage': disk_usage,
            'count': len(metrics),
            'last_updated': now.isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@monitoring_bp.route('/api/performance/metrics')
@login_required
@permission_required('monitor:view')
def api_performance_metrics():
    """获取所有性能指标摘要"""
    try:
        # 获取时间范围参数
        time_range = request.args.get('range', 'hour')
        now = datetime.now(timezone.utc)
        
        if time_range == 'hour':
            start_time = now - timedelta(hours=1)
        elif time_range == 'day':
            start_time = now - timedelta(days=1)
        elif time_range == 'week':
            start_time = now - timedelta(weeks=1)
        else:
            start_time = now - timedelta(hours=1)
        
        # 查询最新的性能指标（按设备分组）
        subquery = db.session.query(
            PerformanceMetric.device_id,
            func.max(PerformanceMetric.timestamp).label('max_timestamp')
        ).filter(
            PerformanceMetric.timestamp >= start_time
        ).group_by(PerformanceMetric.device_id).subquery()
        
        metrics = db.session.query(PerformanceMetric).join(
            subquery,
            db.and_(
                PerformanceMetric.device_id == subquery.c.device_id,
                PerformanceMetric.timestamp == subquery.c.max_timestamp
            )
        ).all()
        
        # 组织数据
        metrics_data = []
        for metric in metrics:
            metrics_data.append({
                'device_id': metric.device_id,
                'device_name': metric.device.name if metric.device else 'Unknown',
                'cpu_usage': metric.cpu_usage,
                'memory_usage': metric.memory_usage,
                'network_usage': metric.network_usage,
                'disk_usage': metric.disk_usage,
                'timestamp': metric.timestamp.isoformat(),
                'status': 'warning' if (metric.cpu_usage or 0) > 80 or (metric.memory_usage or 0) > 85 else 'normal'
            })
        
        return jsonify({
            'metrics': metrics_data,
            'count': len(metrics_data),
            'time_range': time_range,
            'last_updated': now.isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@monitoring_bp.route('/api/alerts')
@login_required
@permission_required('monitor:view')
def api_alerts():
    """获取告警信息"""
    try:
        # 模拟告警数据（在实际应用中应从数据库获取）
        alerts = []
        
        # 检查设备状态
        devices = Device.query.all()
        for device in devices:
            if device.status == 'offline':
                alerts.append({
                    'id': f"alert_{device.id}_{datetime.now(timezone.utc).timestamp()}",
                    'severity': 'critical',
                    'device_id': device.id,
                    'device_name': device.name,
                    'message': f'设备 {device.name} 离线',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'acknowledged': False
                })
            elif device.status == 'warning':
                alerts.append({
                    'id': f"alert_{device.id}_{datetime.now(timezone.utc).timestamp()}",
                    'severity': 'warning',
                    'device_id': device.id,
                    'device_name': device.name,
                    'message': f'设备 {device.name} 状态异常',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'acknowledged': False
                })
        
        # 模拟一些性能告警
        metrics = PerformanceMetric.query.order_by(PerformanceMetric.timestamp.desc()).limit(10).all()
        for metric in metrics:
            if metric.cpu_usage and metric.cpu_usage > 90:
                alerts.append({
                    'id': f"cpu_alert_{metric.id}",
                    'severity': 'warning',
                    'device_id': metric.device_id,
                    'device_name': metric.device.name if metric.device else 'Unknown',
                    'message': f'CPU使用率过高: {metric.cpu_usage}%',
                    'timestamp': metric.timestamp.isoformat(),
                    'acknowledged': False
                })
            if metric.memory_usage and metric.memory_usage > 90:
                alerts.append({
                    'id': f"memory_alert_{metric.id}",
                    'severity': 'warning',
                    'device_id': metric.device_id,
                    'device_name': metric.device.name if metric.device else 'Unknown',
                    'message': f'内存使用率过高: {metric.memory_usage}%',
                    'timestamp': metric.timestamp.isoformat(),
                    'acknowledged': False
                })
        
        # 排序：未确认的优先，然后按严重程度排序
        alerts.sort(key=lambda x: (not x['acknowledged'], 
                                  0 if x['severity'] == 'critical' else 
                                  1 if x['severity'] == 'warning' else 2))
        
        # 统计数据
        alert_stats = {
            'total': len(alerts),
            'critical': sum(1 for a in alerts if a['severity'] == 'critical'),
            'warning': sum(1 for a in alerts if a['severity'] == 'warning'),
            'info': sum(1 for a in alerts if a['severity'] == 'info'),
            'unacknowledged': sum(1 for a in alerts if not a['acknowledged']),
        }
        
        return jsonify({
            'alerts': alerts[:50],  # 只返回最近的50个告警
            'stats': alert_stats,
            'last_updated': datetime.now(timezone.utc).isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@monitoring_bp.route('/api/alerts/<alert_id>/acknowledge', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def api_acknowledge_alert(alert_id):
    """确认告警"""
    try:
        # 在实际应用中，这里应该更新数据库中的告警状态
        # 由于我们使用的是模拟数据，这里只是返回成功响应
        return jsonify({
            'success': True,
            'message': '告警已确认',
            'alert_id': alert_id
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@monitoring_bp.route('/api/settings/monitoring', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def api_monitoring_settings():
    """获取或更新监控设置"""
    if request.method == 'GET':
        try:
            settings = MonitoringSetting.query.all()
            settings_dict = {}
            for setting in settings:
                settings_dict[setting.setting_key] = {
                    'value': setting.get_value(),
                    'type': setting.data_type,
                    'description': setting.description,
                    'category': setting.category
                }
            
            return jsonify(settings_dict)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            category = data.get('category', 'monitoring')
            
            for key, value in data.get('settings', {}).items():
                setting = MonitoringSetting.query.filter_by(
                    setting_key=key,
                    category=category
                ).first()
                
                if not setting:
                    # 创建新设置
                    setting = MonitoringSetting(
                        setting_key=key,
                        category=category,
                        data_type='string',  # 默认为字符串类型
                        created_by=current_user.username
                    )
                    db.session.add(setting)
                
                # 更新设置值
                setting.set_value(value)
                setting.updated_at = datetime.now(timezone.utc)
                setting.updated_by = current_user.username
            
            db.session.commit()

            log_audit(
                action='update',
                resource_type='monitor_setting',
                resource_id='monitoring',
                message='更新监控设置',
                details={'category': category},
                user_id=current_user.id
            )

            return jsonify({'success': True, 'message': '监控设置已保存'})

        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500

# ========== 辅助函数 ==========

def generate_sample_performance_data():
    """生成示例性能数据（用于测试）"""
    devices = Device.query.all()
    now = datetime.now(timezone.utc)
    
    for device in devices:
        # 为每个设备生成一些性能数据
        for i in range(60):  # 生成最近60分钟的数据
            timestamp = now - timedelta(minutes=i)
            
            metric = PerformanceMetric(
                device_id=device.id,
                cpu_usage=random.uniform(10, 70),
                memory_usage=random.uniform(30, 80),
                network_usage=random.uniform(5, 50),
                disk_usage=random.uniform(20, 70),
                timestamp=timestamp,
                created_at=datetime.now(timezone.utc)
            )
            
            # 偶尔制造一些高负载数据
            if random.random() < 0.1:  # 10%的概率
                metric.cpu_usage = random.uniform(80, 99)
                metric.memory_usage = random.uniform(85, 99)
            
            db.session.add(metric)
    
    try:
        db.session.commit()
        print("已生成示例性能数据")
    except Exception as e:
        db.session.rollback()
        print(f"生成示例数据失败: {e}")

def init_monitoring_settings():
    """初始化监控设置"""
    default_settings = [
        # 监控间隔设置
        {
            'key': 'monitoring_interval',
            'value': 60,
            'data_type': 'number',
            'category': 'monitoring',
            'description': '监控数据采集间隔（秒）'
        },
        {
            'key': 'data_retention_days',
            'value': 30,
            'data_type': 'number',
            'category': 'monitoring',
            'description': '性能数据保留天数'
        },
        # 告警阈值设置
        {
            'key': 'cpu_warning_threshold',
            'value': 80,
            'data_type': 'number',
            'category': 'alerts',
            'description': 'CPU使用率警告阈值（%）'
        },
        {
            'key': 'cpu_critical_threshold',
            'value': 90,
            'data_type': 'number',
            'category': 'alerts',
            'description': 'CPU使用率严重阈值（%）'
        },
        {
            'key': 'memory_warning_threshold',
            'value': 85,
            'data_type': 'number',
            'category': 'alerts',
            'description': '内存使用率警告阈值（%）'
        },
        {
            'key': 'memory_critical_threshold',
            'value': 95,
            'data_type': 'number',
            'category': 'alerts',
            'description': '内存使用率严重阈值（%）'
        },
        {
            'key': 'disk_warning_threshold',
            'value': 80,
            'data_type': 'number',
            'category': 'alerts',
            'description': '磁盘使用率警告阈值（%）'
        },
        {
            'key': 'disk_critical_threshold',
            'value': 90,
            'data_type': 'number',
            'category': 'alerts',
            'description': '磁盘使用率严重阈值（%）'
        },
        # 通知设置
        {
            'key': 'email_notifications',
            'value': True,
            'data_type': 'boolean',
            'category': 'notifications',
            'description': '启用邮件通知'
        },
        {
            'key': 'email_recipients',
            'value': 'admin@example.com',
            'data_type': 'string',
            'category': 'notifications',
            'description': '告警邮件接收人'
        },
    ]
    
    for setting_data in default_settings:
        setting = MonitoringSetting.query.filter_by(
            setting_key=setting_data['key'],
            category=setting_data['category']
        ).first()
        
        if not setting:
            setting = MonitoringSetting(
                setting_key=setting_data['key'],
                data_type=setting_data['data_type'],
                category=setting_data['category'],
                description=setting_data['description'],
                created_by='system'
            )
            setting.set_value(setting_data['value'])
            db.session.add(setting)
    
    try:
        db.session.commit()
        print("监控设置初始化完成")
    except Exception as e:
        db.session.rollback()
        print(f"监控设置初始化失败: {e}")





@monitoring_bp.route('/api/interfaces/<int:interface_id>/history')
@login_required
@permission_required('monitor:view')
def interface_history(interface_id):
    hours = request.args.get('hours', 24, type=int)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    records = InterfaceMonitorData.query.filter(
        InterfaceMonitorData.interface_id == interface_id,
        InterfaceMonitorData.collected_at >= since
    ).order_by(InterfaceMonitorData.collected_at).all()
    data = [{
        'timestamp': r.collected_at.isoformat(),
        'bytes_in': r.bytes_in,
        'bytes_out': r.bytes_out,
        'speed_in': None,
        'speed_out': None,
        'bandwidth_usage': r.bandwidth_usage
    } for r in records]

    return jsonify(data)


@monitoring_bp.route('/api/devices/<int:device_id>/discover-interfaces', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def discover_interfaces(device_id):
    """手动触发接口发现（通过 SNMP 获取接口列表并保存）"""
    device = Device.query.get_or_404(device_id)
    ip = device.management_ip or device.ip_address
    community = getattr(device, 'snmp_community', 'public')
    version = getattr(device, 'snmp_version', '2c')
    port = getattr(device, 'snmp_port', 161)

    if not ip:
        return jsonify({'success': False, 'message': '设备没有 IP 地址'}), 400

    try:
        # 调用 SNMP 发现函数获取接口列表
        discovered = snmp_discover_interfaces_real(ip, community, version, port)
        if not discovered:
            return jsonify({'success': False, 'message': '未发现任何接口，请检查 SNMP 配置'})

        # 保存到数据库
        saved = save_discovered_interfaces(device_id, discovered)

        log_audit(
            action='execute',
            resource_type='device_interface',
            resource_id=device_id,
            message=f'发现并保存接口: 设备ID={device_id}',
            details={'discovered': len(discovered), 'saved': len(saved)},
            user_id=current_user.id if hasattr(current_user, 'id') else None
        )

        return jsonify({
            'success': True,
            'message': f'发现 {len(discovered)} 个接口，保存 {len(saved)} 个',
            'interfaces': saved
        })
    except Exception as e:
        logger.error(f"接口发现失败: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


#==================================================================

# ------------------- 页面路由 -------------------
@monitoring_bp.route('/interface_monitor')
@login_required
@permission_required('monitor:view')
def interface_monitor():
    """接口监控页面（已有，但确保传入数据格式正确）"""
    device_id = request.args.get('device_id', type=int)
    devices = Device.query.order_by(Device.name).all()
    interfaces = []
    interface_stats = {}
    connections = []
    device = None

    if device_id:
        device = Device.query.get_or_404(device_id)
        interfaces = Interface.query.filter_by(device_id=device_id).all()
        for iface in interfaces:
            latest = InterfaceMonitorData.query.filter_by(interface_id=iface.id) \
                        .order_by(InterfaceMonitorData.collected_at.desc()).first()
            if latest:
                interface_stats[iface.id] = {
                    'bytes_in': latest.bytes_in,
                    'bytes_out': latest.bytes_out,
                    'bandwidth_usage': latest.bandwidth_usage,
                    'admin_status': latest.admin_status,
                    'oper_status': latest.oper_status,
                    'last_updated': latest.collected_at
                }
        # 连接关系处理
        conn_paths = ConnectionPath.query.filter(
            (ConnectionPath.source_device_id == device_id) | (ConnectionPath.target_device_id == device_id)
        ).all()
        for conn in conn_paths:
            if conn.source_device_id == device_id:
                source_port = conn.source_interface.name if conn.source_interface else '未知端口'
                target_device = conn.target_device
                target_port = conn.target_interface.name if conn.target_interface else '未知端口'
            else:
                source_port = conn.target_interface.name if conn.target_interface else '未知端口'
                target_device = conn.source_device
                target_port = conn.source_interface.name if conn.source_interface else '未知端口'
            connections.append({
                'source_port': source_port,
                'connection_type': conn.connection_type,
                'target_device': target_device,
                'target_port': target_port,
                'link_status': conn.link_status,
                'bandwidth': conn.bandwidth
            })

    return render_template('monitoring/interface_monitor.html',
                           devices=devices,
                           interfaces=interfaces,
                           interface_stats=interface_stats,
                           connections=connections,
                           device=device,
                           device_id=device_id)


# ------------------- 获取指定设备所有接口的最新监控数据 API 路由 -------------------
@monitoring_bp.route('/api/devices/<int:device_id>/interfaces/latest')
@login_required
@permission_required('monitor:view')
def get_latest_interface_stats(device_id):
    """获取指定设备所有接口的最新监控数据"""
    # 确认设备存在
    print("get_latest_interface_stats called, device_id:", device_id)
    device = Device.query.get_or_404(device_id)
    # 查询该设备所有接口
    interfaces = Interface.query.filter_by(device_id=device_id).all()
    result = []
    for iface in interfaces:
        latest = InterfaceMonitorData.query.filter_by(interface_id=iface.id) \
                    .order_by(InterfaceMonitorData.collected_at.desc()).first()
        if latest:
            result.append({
                'interface_id': iface.id,
                'bytes_in': latest.bytes_in,
                'bytes_out': latest.bytes_out,
                'speed_in': latest.speed_in,      # 新增
                'speed_out': latest.speed_out,    # 新增
                'bandwidth_usage': latest.bandwidth_usage,
                'admin_status': latest.admin_status,
                'oper_status': latest.oper_status,
                'last_updated': latest.collected_at.isoformat() if latest.collected_at else None
            })
    return jsonify(result)


@monitoring_bp.route('/api/devices/<int:device_id>/interface-trend')
@login_required
@permission_required('monitor:view')
def get_interface_trend(device_id):
    """获取设备所有接口的流量趋势（最近 hours 小时，默认6小时）"""
    hours = request.args.get('hours', 6, type=int)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    # 查询该设备所有接口在时间范围内的监控数据，按接口和时间排序
    data = InterfaceMonitorData.query.filter(
        InterfaceMonitorData.device_id == device_id,
        InterfaceMonitorData.collected_at >= since
    ).order_by(InterfaceMonitorData.collected_at).all()

    # 按采集时间分组，构造 Chart.js 需要的数据集
    # 这里简化：返回每个接口的入站和出站流量（平均值或最新值？通常趋势图需要每个时间点的值）
    # 为了简化，我们返回每个时间点的汇总（所有接口的总流量）或者按接口分别展示
    # 前端期望的格式：{ labels: [时间点], datasets: [ { label: '接口名 入站', data: [...] }, ... ] }
    # 这里实现一个较通用的版本：返回最近 hours 小时内每小时的聚合数据（平均流量）
    # 更好的做法：返回每个接口单独的数据集，但数据量可能很大。这里以小时为单位聚合。

    from collections import defaultdict
    import numpy as np

    # 按小时分组
    hourly_stats = defaultdict(lambda: {'bytes_in': 0, 'bytes_out': 0, 'count': 0})
    for d in data:
        hour_key = d.collected_at.replace(minute=0, second=0, microsecond=0)
        hourly_stats[hour_key]['bytes_in'] += d.bytes_in
        hourly_stats[hour_key]['bytes_out'] += d.bytes_out
        hourly_stats[hour_key]['count'] += 1

    # 排序
    sorted_hours = sorted(hourly_stats.keys())
    labels = [h.strftime('%H:%M') for h in sorted_hours]
    avg_in = [hourly_stats[h]['bytes_in'] / hourly_stats[h]['count'] / 1024 / 1024 for h in sorted_hours]  # MB
    avg_out = [hourly_stats[h]['bytes_out'] / hourly_stats[h]['count'] / 1024 / 1024 for h in sorted_hours]

    chart_data = {
        'labels': labels,
        'datasets': [
            {
                'label': '平均入站流量 (MB)',
                'data': avg_in,
                'borderColor': 'rgb(40, 167, 69)',
                'backgroundColor': 'rgba(40, 167, 69, 0.1)',
                'tension': 0.3
            },
            {
                'label': '平均出站流量 (MB)',
                'data': avg_out,
                'borderColor': 'rgb(220, 53, 69)',
                'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                'tension': 0.3
            }
        ]
    }
    return jsonify(chart_data)


@monitoring_bp.route('/api/interfaces/<int:interface_id>/history')
@login_required
@permission_required('monitor:view')
def get_interface_history(interface_id):
    try:
        hours = request.args.get('hours', 24, type=int)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        records = InterfaceMonitorData.query.filter(
            InterfaceMonitorData.interface_id == interface_id,
            InterfaceMonitorData.collected_at >= since
        ).order_by(InterfaceMonitorData.collected_at).all()
        result = []
        for r in records:
            result.append({
                'timestamp': r.collected_at.isoformat() if r.collected_at else None,
                'bytes_in': r.bytes_in,
                'bytes_out': r.bytes_out,
                'speed_in': r.speed_in,            # 新增
                'speed_out': r.speed_out,          # 新增
                'bandwidth_usage': r.bandwidth_usage
            })
        return jsonify(result)
    except Exception as e:
        print("Error in get_interface_history:", e)
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@monitoring_bp.route('/api/interfaces/<int:interface_id>')
@login_required
@permission_required('monitor:view')
def get_interface_detail(interface_id):
    """获取接口详细信息（包括邻居信息）"""
    interface = Interface.query.get_or_404(interface_id)
    latest = InterfaceMonitorData.query.filter_by(interface_id=interface_id) \
                .order_by(InterfaceMonitorData.collected_at.desc()).first()
    # 查找邻居信息（假设通过 ConnectionPath 关联）
    neighbor = None
    # 查找该接口作为源或目标的连接
    conn = ConnectionPath.query.filter(
        (ConnectionPath.source_interface_id == interface_id) | (ConnectionPath.target_interface_id == interface_id)
    ).first()
    if conn:
        if conn.source_interface_id == interface_id:
            neighbor_device = conn.target_device
            neighbor_interface = conn.target_interface
        else:
            neighbor_device = conn.source_device
            neighbor_interface = conn.source_interface
        neighbor = {
            'device_id': neighbor_device.id if neighbor_device else None,
            'device_name': neighbor_device.name if neighbor_device else None,
            'interface_name': neighbor_interface.name if neighbor_interface else None,
            'ip': neighbor_interface.ip_address if neighbor_interface else None
        }
    data = {
        'id': interface.id,
        'name': interface.name,
        'description': interface.description,
        'mac_address': interface.mac_address,
        'ip_address': interface.ip_address,
        'subnet_mask': interface.subnet_mask,
        'mtu': interface.mtu,
        'admin_status': latest.admin_status if latest else None,
        'oper_status': latest.oper_status if latest else None,
        'speed': latest.speed if latest else None,
        'neighbor_device_id': neighbor['device_id'] if neighbor else None,
        'neighbor_device': {'name': neighbor['device_name']} if neighbor else None,
        'neighbor_interface': neighbor['interface_name'] if neighbor else None,
        'neighbor_ip': neighbor['ip'] if neighbor else None
    }
    return jsonify(data)


@monitoring_bp.route('/api/export/interfaces')
@login_required
@permission_required('monitor:view')
def export_interfaces_csv():
    """导出接口数据为 CSV 文件"""
    device_id = request.args.get('device_id', type=int)
    if not device_id:
        return "Missing device_id", 400
    interfaces = Interface.query.filter_by(device_id=device_id).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['接口名', 'IP地址', '管理状态', '运行状态', '入流量(B)', '出流量(B)', '带宽使用率(%)', '最后更新时间'])
    for iface in interfaces:
        latest = InterfaceMonitorData.query.filter_by(interface_id=iface.id) \
                    .order_by(InterfaceMonitorData.collected_at.desc()).first()
        if latest:
            writer.writerow([
                iface.name,
                iface.ip_address or '',
                latest.admin_status or '',
                latest.oper_status or '',
                latest.bytes_in or 0,
                latest.bytes_out or 0,
                latest.bandwidth_usage or 0,
                latest.collected_at.strftime('%Y-%m-%d %H:%M:%S') if latest.collected_at else ''
            ])
        else:
            writer.writerow([iface.name, iface.ip_address or '', '', '', 0, 0, 0, ''])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment;filename=interfaces_device_{device_id}.csv"}
    )



@monitoring_bp.route('/api/trigger-poll', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def trigger_poll():
    try:
        poll_all_devices_interfaces(current_app._get_current_object())
        log_audit(
            action='execute',
            resource_type='monitor_data',
            resource_id='poll',
            message='手动触发采集任务',
            user_id=current_user.id if hasattr(current_user, 'id') else None
        )
        return jsonify({'success': True, 'message': '采集任务已手动触发'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@monitoring_bp.route('/device_config/<int:config_id>/alert_rule', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def add_alert_rule(config_id):
    data = request.get_json()
    rule = AlertRule(
        device_config_id=config_id,
        metric_name=data['metric_name'],
        operator=data['operator'],
        threshold=data['threshold'],
        duration=data.get('duration', 60),
        notify_channels=data.get('notify_channels', []),
        notify_targets=data.get('notify_targets', [])
    )
    db.session.add(rule)
    db.session.commit()
    log_audit(
        action='create',
        resource_type='alert_rule',
        resource_id=rule.id,
        message=f'新增告警规则: {rule.metric_name}',
        details={'config_id': config_id},
        user_id=current_user.id if hasattr(current_user, 'id') else None
    )
    return jsonify({'success': True})

@monitoring_bp.route('/alerts')
def alert_history():
    page = request.args.get('page', 1, type=int)
    device_id = request.args.get('device_id')
    status = request.args.get('status', 'all')
    query = AlertHistory.query
    if device_id:
        query = query.join(DeviceConfig).filter(DeviceConfig.device_id == device_id)
    if status != 'all':
        query = query.filter_by(status=status)
    pagination = query.order_by(AlertHistory.triggered_at.desc()).paginate(page=page, per_page=20)
    return render_template('monitoring/alert_history.html', pagination=pagination)

