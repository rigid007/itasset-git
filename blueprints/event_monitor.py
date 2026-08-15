"""
blueprints/event_monitor.py — 事件驱动监控的控制 API

提供：状态查询、启停、以及用于测试/外部系统推送的"事件注入"接口。
"""
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required
from utils.permission import permission_required
from services.event_monitor import event_monitor

event_monitor_bp = Blueprint('event_monitor', __name__, url_prefix='/api/event_monitor')


@event_monitor_bp.route('/status', methods=['GET'])
@login_required
@permission_required('monitor:view')
def status():
    """查询事件监控运行状态与最近一次事件"""
    return jsonify({
        'success': True,
        'data': {
            'running': event_monitor.running,
            'enabled': event_monitor.enabled,
            'pysnmp': event_monitor._pysnmp,
            'trap_port': event_monitor.trap_port,
            'syslog_port': event_monitor.syslog_port,
            'received_count': event_monitor.received_count,
            'last_event': event_monitor.last_event,
        }
    })


@event_monitor_bp.route('/start', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def start():
    """手动启动事件监控（默认应用启动时已自动启动）"""
    event_monitor.app = current_app._get_current_object()
    event_monitor.start()
    return jsonify({'success': True, 'message': '事件监控已启动'})


@event_monitor_bp.route('/stop', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def stop():
    """停止事件监控"""
    event_monitor.stop()
    return jsonify({'success': True, 'message': '事件监控已停止'})


@event_monitor_bp.route('/inject', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def inject():
    """注入一次设备状态事件（测试或外部系统主动推送用）

    请求体（JSON 或表单）：
        ip      必填，设备管理 IP
        status  必填，online / offline
        source  可选，事件来源标记（默认 event）
    """
    data = request.get_json(silent=True) or request.form
    ip = data.get('ip')
    status = str(data.get('status', '')).lower()
    source = data.get('source', 'event')
    if not ip or status not in ('online', 'offline'):
        return jsonify({'success': False, 'message': '需要 ip 和 status(online/offline)'}), 400
    dev = event_monitor.apply_device_event(ip, status, source, 'manual inject')
    if dev:
        return jsonify({'success': True, 'data': {'device': dev.name, 'status': dev.status}})
    return jsonify({'success': False, 'message': f'未匹配到 IP={ip} 的设备'}), 404
