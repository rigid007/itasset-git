# blueprints/api.py

from flask import Blueprint, jsonify, request, Response
from flask_login import login_required, current_user
from datetime import timedelta
from extensions import db
from models.models import OperationLog, ActivityLog
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