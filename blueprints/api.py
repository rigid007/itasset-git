# blueprints/api.py

from flask import Blueprint, jsonify, request, Response
from flask_login import login_required, current_user
from datetime import datetime, timedelta, timezone
from extensions import db
from models.models import ConnectionPath, Device, OperationLog, ActivityLog, User
import json
from utils.audit import log_audit
from utils.permission import permission_required

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/user/recent-activities')
@login_required
@permission_required('user:view')
def user_recent_activities():
    """获取用户最近活动"""
    logs = OperationLog.query.filter_by(user_id=current_user.id)\
        .order_by(OperationLog.created_at.desc())\
        .limit(10).all()
    
    return jsonify({
        'success': True,
        'data': [{
            'created_at': (log.created_at + timedelta(hours=8)).isoformat() if log.created_at else None,
            'action': log.operation_type,  # 修改这里：使用 operation_type
            'ip_address': log.ip_address,
            'details': log.details,
            'resource_type': log.resource_type,
            'resource_name': log.resource_name
        } for log in logs]
    })

@api_bp.route('/user/export-data')
@login_required
@permission_required('user:view')
def export_user_data():
    """导出用户数据"""
    export_basic = request.args.get('basic', 'false').lower() == 'true'
    export_logs = request.args.get('logs', 'false').lower() == 'true'
    
    data = {}
    
    if export_basic:
        data['basic'] = {
            'username': current_user.username,
            'email': current_user.email,
            'phone': current_user.phone if hasattr(current_user, 'phone') else '',
            'department': current_user.department if hasattr(current_user, 'department') else '',
            'role': current_user.role if hasattr(current_user, 'role') else 'user',
            'created_at': (current_user.created_at + timedelta(hours=8)).isoformat() if hasattr(current_user, 'created_at') and current_user.created_at else None,
            'last_login': (current_user.last_login + timedelta(hours=8)).isoformat() if hasattr(current_user, 'last_login') and current_user.last_login else None
        }
    
    if export_logs:
        logs = OperationLog.query.filter_by(user_id=current_user.id)\
            .order_by(OperationLog.created_at.desc())\
            .limit(100).all()
        data['logs'] = [{
            'action': log.operation_type,  # 修改这里：使用 operation_type
            'details': log.details,
            'created_at': (log.created_at + timedelta(hours=8)).isoformat() if log.created_at else None,
            'ip_address': log.ip_address,
            'resource_type': log.resource_type,
            'resource_name': log.resource_name
        } for log in logs]
    
    response = Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        mimetype='application/json'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=user_data_{current_user.username}.json'
    
    return response

@api_bp.route('/devices')
@login_required
@permission_required('device:view')
def api_devices():
    """供运维页面下拉框使用的设备简要列表。"""
    devices = Device.query.order_by(Device.name.asc()).all()
    return jsonify({'success': True, 'devices': [{
        'id': d.id,
        'name': d.name,
        'hostname': d.name,
        'ip_address': d.ip_address or d.management_ip or '',
        'model': d.model or '',
        'status': d.status or '',
    } for d in devices]})


@api_bp.route('/users')
@login_required
@permission_required('user:view')
def api_users():
    """供运维页面下拉框使用的用户简要列表。"""
    users = User.query.order_by(User.username.asc()).all()
    return jsonify({'success': True, 'users': [{
        'id': u.id,
        'username': u.username,
        'name': getattr(u, 'name', None) or u.username,
        'department': getattr(u, 'department', None),
    } for u in users]})


def _as_naive_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _link_aging(link, now):
    last_seen = _as_naive_utc(link.last_seen)
    if not last_seen:
        if link.link_status == 'stale':
            return {'state': 'stale', 'label': '已老化', 'hours': None}
        return {'state': 'unknown', 'label': '未记录', 'hours': None}
    hours = max(0.0, (now - last_seen).total_seconds() / 3600.0)
    if link.link_status == 'stale' or hours > 72:
        return {'state': 'stale', 'label': '已老化', 'hours': round(hours, 1)}
    if hours > 24:
        return {'state': 'aging', 'label': '老化中', 'hours': round(hours, 1)}
    return {'state': 'fresh', 'label': '正常', 'hours': round(hours, 1)}


@api_bp.route('/topology-data')
@login_required
@permission_required('topology:view')
def topology_data():
    """ECharts topology data endpoint.

    Matches templates/topology_view.html expectations: nodes and links arrays.
    Each link carries ConnectionPath discovery_protocol/discovered_by, confidence,
    last_seen and computed aging state for display in the topology page.
    """
    devices = Device.query.all()
    connections = ConnectionPath.query.all()

    device_map = {}
    nodes = []
    for d in devices:
        node = {
            'id': str(d.id),
            'name': d.name,
            'type': d.device_type or 'unknown',
            'status': d.status or 'unknown',
            'ip': d.management_ip or d.ip_address or '',
            'vendor': d.brand or d.manufacturer or '',
            'model': d.model or '',
            'mac': d.mac_address or '',
            'last_seen': d.last_seen.isoformat() if d.last_seen else None,
        }
        nodes.append(node)
        device_map[d.id] = node

    now = datetime.utcnow()
    links = []
    for c in connections:
        source_node = device_map.get(c.source_device_id)
        target_node = device_map.get(c.target_device_id)
        aging = _link_aging(c, now)
        links.append({
            'id': c.id,
            'source': str(c.source_device_id),
            'target': str(c.target_device_id),
            'source_name': source_node['name'] if source_node else f"ID:{c.source_device_id}",
            'target_name': target_node['name'] if target_node else f"ID:{c.target_device_id}",
            'source_if': c.source_port or '',
            'target_if': c.target_port or '',
            'protocol': c.discovery_protocol or c.discovered_by or 'unknown',
            'confidence': c.confidence if c.confidence is not None else 0,
            'bandwidth': c.bandwidth or 0,
            'media': c.media_type or '',
            'vlan': c.vlan_id or '',
            'status': c.link_status or 'unknown',
            'type': c.connection_type or 'physical',
            'aging_state': aging['state'],
            'aging_label': aging['label'],
            'aging_hours': aging['hours'],
            'last_seen': c.last_seen.isoformat() if c.last_seen else None,
        })

    return jsonify({
        'nodes': nodes,
        'links': links,
        'timestamp': now.isoformat(),
    })
