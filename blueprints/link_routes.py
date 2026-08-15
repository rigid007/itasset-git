"""
链路监控API路由
"""
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required
from sqlalchemy import and_, or_, func, case

from extensions import db
from utils.audit import log_audit
from utils.permission import permission_required
from models.models import ConnectionPath, Device, Interface, DeviceMonitorLog, AlertEvent
from tasks.link_monitor import LinkMonitor

link_bp = Blueprint('link', __name__, url_prefix='/api/links')


@link_bp.route('/status', methods=['GET'])
@login_required
@permission_required('topology:view')
def get_link_status():
    """获取所有链路状态"""
    links = ConnectionPath.query.all()
    
    result = []
    for link in links:
        result.append({
            'id': link.id,
            'source_device': link.source_device.name if link.source_device else None,
            'source_port': link.source_port,
            'target_device': link.target_device.name if link.target_device else None,
            'target_port': link.target_port,
            'status': link.link_status,
            'connection_type': link.connection_type,
            'discovery_protocol': link.discovery_protocol,
            'last_updated': link.updated_at.isoformat() if link.updated_at else None
        })
    
    return jsonify({
        'success': True,
        'data': result,
        'total': len(result)
    })


@link_bp.route('/check', methods=['POST'])
@login_required
@permission_required('topology:edit')
def check_links():
    """手动触发链路检测"""
    data = request.get_json() or {}
    connection_ids = data.get('connection_ids')
    
    monitor = current_app.link_monitor
    results = monitor.check_all_links(connection_ids)

    log_audit('execute', 'link', 0, '手动触发链路检测',
              details={'connection_ids': connection_ids})

    return jsonify({
        'success': True,
        'data': results,
        'total': len(results)
    })


@link_bp.route('/discover', methods=['POST'])
@login_required
@permission_required('topology:edit')
def discover_links():
    """LLDP自动发现链路"""
    data = request.get_json() or {}
    device_ids = data.get('device_ids')
    
    monitor = current_app.link_monitor
    result = monitor.discover_links_via_lldp(device_ids)

    log_audit('create', 'link', 0, 'LLDP自动发现链路',
              details={'device_ids': device_ids})

    return jsonify({
        'success': True,
        'data': result
    })


@link_bp.route('/sync', methods=['POST'])
@login_required
@permission_required('topology:edit')
def sync_topology():
    """同步完整拓扑"""
    monitor = current_app.link_monitor
    result = monitor.sync_topology()

    log_audit('execute', 'topology', 0, '同步完整拓扑',
              details={'result': result})

    return jsonify({
        'success': True,
        'data': result
    })


@link_bp.route('/history/<int:connection_id>', methods=['GET'])
@login_required
@permission_required('topology:view')
def get_link_history(connection_id):
    """获取指定链路的历史状态"""
    # 修复：原来未按 connection_id 过滤，返回的是全局最近 100 条链路日志
    # 现在按 device_id 过滤（ConnectionPath 关联的源/目标设备）+ monitor_type
    conn = ConnectionPath.query.get(connection_id)
    if not conn:
        return jsonify({'success': False, 'message': '链路不存在'}), 404

    # 取源设备和目标设备 ID，查询与该链路相关的监控日志
    device_ids = []
    if conn.source_device:
        device_ids.append(conn.source_device.id)
    if conn.target_device:
        device_ids.append(conn.target_device.id)

    logs = DeviceMonitorLog.query.filter(
        DeviceMonitorLog.monitor_type == 'link_monitor',
        DeviceMonitorLog.device_id.in_(device_ids) if device_ids else False
    ).order_by(DeviceMonitorLog.created_at.desc()).limit(100).all()

    result = []
    for log in logs:
        result.append({
            'id': log.id,
            'device_id': log.device_id,
            'device_ip': log.device_ip,
            'old_status': log.old_status,
            'new_status': log.new_status,
            'is_online': log.is_online,
            'error_message': log.error_message,
            'created_at': log.created_at.isoformat() if log.created_at else None
        })

    return jsonify({
        'success': True,
        'data': result
    })


@link_bp.route('/stats', methods=['GET'])
@login_required
@permission_required('topology:view')
def get_link_stats():
    """获取链路统计信息（单次聚合查询优化）"""
    # 用一条 GROUP BY 查询替代 4 次独立 COUNT
    rows = db.session.query(
        ConnectionPath.link_status,
        func.count(ConnectionPath.id)
    ).group_by(ConnectionPath.link_status).all()

    status_map = {row[0]: row[1] for row in rows}
    total = sum(status_map.values())
    active = status_map.get('active', 0)
    down = status_map.get('down', 0)
    unknown = status_map.get('unknown', 0)

    return jsonify({
        'success': True,
        'data': {
            'total': total,
            'active': active,
            'down': down,
            'unknown': unknown,
            'active_rate': round(active / total * 100, 2) if total > 0 else 0
        }
    })


@link_bp.route('/quick_status', methods=['GET'])
@login_required
@permission_required('topology:view')
def get_quick_status():
    """快速状态查询：一次请求返回设备离线 + 链路 down + 活跃告警

    优化点：
    - 设备状态用 GROUP BY 单次聚合（利用 idx_devices_status 索引）
    - 链路状态用 GROUP BY 单次聚合（利用 idx_connection_paths_link_status 索引）
    - 离线设备 / down 链路只返回精简字段（id/name/ip），避免全量序列化
    - 活跃告警用 COUNT 聚合
    """
    import time as _time
    t0 = _time.time()

    # ---- 设备状态聚合（排除已下架）----
    dev_rows = db.session.query(
        Device.status,
        func.count(Device.id)
    ).filter(
        Device.is_decommissioned == False
    ).group_by(Device.status).all()

    dev_status_map = {row[0]: row[1] for row in dev_rows}
    dev_total = sum(dev_status_map.values())
    dev_online = dev_status_map.get('online', 0)
    dev_offline = dev_status_map.get('offline', 0)
    dev_warning = dev_status_map.get('warning', 0)
    dev_unknown = dev_status_map.get('unknown', 0)
    dev_maintenance = dev_status_map.get('maintenance', 0)

    # ---- 链路状态聚合 ----
    link_rows = db.session.query(
        ConnectionPath.link_status,
        func.count(ConnectionPath.id)
    ).group_by(ConnectionPath.link_status).all()

    link_status_map = {row[0]: row[1] for row in link_rows}
    link_total = sum(link_status_map.values())
    link_active = link_status_map.get('active', 0)
    link_down = link_status_map.get('down', 0)
    link_unknown = link_status_map.get('unknown', 0)

    # ---- 离线设备列表（精简字段，最多返回 200 条）----
    offline_devices = []
    if dev_offline > 0:
        offline_devs = Device.query.filter(
            Device.status == 'offline',
            Device.is_decommissioned == False
        ).with_entities(
            Device.id, Device.name, Device.management_ip,
            Device.last_checked, Device.ip_address
        ).order_by(Device.last_checked.desc()).limit(200).all()
        offline_devices = [
            {
                'id': d.id,
                'name': d.name,
                'ip': d.management_ip or d.ip_address,
                'last_checked': d.last_checked.isoformat() if d.last_checked else None
            }
            for d in offline_devs
        ]

    # ---- down 链路列表（精简字段，最多返回 200 条）----
    down_links = []
    if link_down > 0:
        down_conns = ConnectionPath.query.filter(
            ConnectionPath.link_status == 'down'
        ).order_by(ConnectionPath.updated_at.desc()).limit(200).all()
        down_links = [
            {
                'id': c.id,
                'source_device': c.source_device.name if c.source_device else None,
                'source_port': c.source_port,
                'target_device': c.target_device.name if c.target_device else None,
                'target_port': c.target_port,
                'last_updated': c.updated_at.isoformat() if c.updated_at else None
            }
            for c in down_conns
        ]

    # ---- 活跃告警数 ----
    try:
        active_alerts = db.session.query(func.count(AlertEvent.id)).filter(
            AlertEvent.status.in_(['active', 'acknowledged'])
        ).scalar() or 0
    except Exception:
        active_alerts = 0

    elapsed_ms = round((_time.time() - t0) * 1000, 1)

    return jsonify({
        'success': True,
        'data': {
            'devices': {
                'total': dev_total,
                'online': dev_online,
                'offline': dev_offline,
                'warning': dev_warning,
                'unknown': dev_unknown,
                'maintenance': dev_maintenance,
                'online_rate': round(dev_online / dev_total * 100, 2) if dev_total > 0 else 0,
                'offline_list': offline_devices,
            },
            'links': {
                'total': link_total,
                'active': link_active,
                'down': link_down,
                'unknown': link_unknown,
                'active_rate': round(link_active / link_total * 100, 2) if link_total > 0 else 0,
                'down_list': down_links,
            },
            'alerts': {
                'active': active_alerts,
            },
            'query_time_ms': elapsed_ms,
            'timestamp': _time.strftime('%Y-%m-%dT%H:%M:%S')
        }
    })