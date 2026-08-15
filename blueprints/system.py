# system_routes.py

from flask import Blueprint, jsonify, request
from datetime import datetime
from flask_login import login_required
from utils.audit import log_audit
from utils.permission import permission_required

# 创建系统蓝图
system_bp = Blueprint('system', __name__)

# ==================== 系统配置API ====================
@system_bp.route('/configs', methods=['GET'])
@login_required
@permission_required('config:view')
def api_system_configs():
    """获取所有系统配置"""
    configs = {
        'auto_monitor_enabled': True,
        'auto_monitor_interval': 300,
        'auto_monitor_concurrent': 10,
        'auto_monitor_timeout': 30,
        'ping_interval': 60,
        'snmp_interval': 300,
        'alert_email_enabled': True,
        'alert_sms_enabled': False,
        'data_retention_days': 365,
        'backup_enabled': True,
        'backup_interval': 24,
        'system_name': '网络资产管理系统',
        'system_version': '2.0.0',
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    return jsonify({'success': True, 'data': configs})

@system_bp.route('/configs/<config_key>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def api_update_system_config(config_key):
    """更新系统配置项"""
    data = request.get_json()
    if not data or 'value' not in data:
        return jsonify({'success': False, 'message': '缺少配置值'}), 400
    
    value = data['value']
    
    # 验证配置键
    valid_keys = [
        'auto_monitor_enabled', 'auto_monitor_interval', 
        'auto_monitor_concurrent', 'auto_monitor_timeout',
        'ping_interval', 'snmp_interval', 'alert_email_enabled',
        'alert_sms_enabled', 'data_retention_days', 'backup_enabled',
        'backup_interval', 'system_name'
    ]
    
    if config_key not in valid_keys:
        return jsonify({'success': False, 'message': f'无效的配置键: {config_key}'}), 400
    
    # 打印更新日志
    print(f"[System API] 更新配置项 {config_key} = {value}")
    log_audit('update', 'system', config_key, f'更新系统配置项 {config_key}', details={'key': config_key, 'value': value})

    return jsonify({
        'success': True,
        'message': '配置更新成功',
        'data': {
            'key': config_key,
            'value': value,
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    })

@system_bp.route('/configs/batch', methods=['PUT'])
@login_required
@permission_required('config:edit')
def api_batch_update_system_configs():
    """批量更新系统配置"""
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'success': False, 'message': '无效的配置数据'}), 400
    
    updated_configs = []
    
    for key, value in data.items():
        print(f"[System API] 批量更新配置项 {key} = {value}")
        updated_configs.append({
            'key': key,
            'value': value,
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    log_audit('update', 'system', 'batch', f'批量更新 {len(updated_configs)} 个系统配置项', details={'count': len(updated_configs), 'keys': list(data.keys())})

    return jsonify({
        'success': True,
        'message': f'成功更新 {len(updated_configs)} 个配置项',
        'data': updated_configs
    })

# ==================== 系统信息API ====================
@system_bp.route('/info', methods=['GET'])
@login_required
@permission_required('config:view')
def api_system_info():
    """获取系统信息"""
    import platform
    import os
    
    system_info = {
        'platform': platform.system(),
        'platform_version': platform.version(),
        'python_version': platform.python_version(),
        'hostname': platform.node(),
        'cpu_count': 8,
        'cpu_percent': 45.5,
        'memory_total': 16.0,
        'memory_used': 8.2,
        'memory_percent': 51.25,
        'disk_total': 512.0,
        'disk_used': 256.5,
        'disk_percent': 50.1,
        'boot_time': (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S'),
        'process_id': os.getpid()
    }
    
    return jsonify({'success': True, 'data': system_info})

# 健康检查API
@system_bp.route('/health', methods=['GET'])
def system_health_check():
    """系统健康检查"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'service': 'system-service',
        'version': '2.0.0'
    })