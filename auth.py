# from functools import wraps
# from flask import request, current_app, jsonify
# from flask_login import current_user
# import jwt
# from datetime import datetime,timezone
# from extensions import db
# from models.models import  OperationLog,User

# def admin_required(f):
#     """要求管理员权限的装饰器"""
#     @wraps(f)
#     def decorated_function(*args, **kwargs):
#         if not current_user.is_authenticated:
#             return jsonify({'error': 'Authentication required'}), 401
#         if not current_user.is_admin:
#             return jsonify({'error': 'Admin privileges required'}), 403
#         return f(*args, **kwargs)
#     return decorated_function




# def log_operation(operation_type, resource_type=None, resource_id=None, resource_name=None, details=None, user=None):
#     """
#     记录操作日志
#     Args:
#         operation_type: 操作类型 (如 'create', 'update', 'delete')
#         resource_type: 资源类型 (如 'device', 'cabinet')
#         resource_id: 资源ID
#         resource_name: 资源名称
#         details: 操作详情
#         user: 可选的用户对象（优先使用），若未提供则尝试从 current_user 获取
#     """
#     # 确定用户信息
#     user_id = None
#     username = "系统"

#     if user and hasattr(user, 'id'):
#         user_id = user.id
#         username = getattr(user, 'username', '未知用户')
#     elif hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
#         user_id = current_user.id
#         username = getattr(current_user, 'username', '未知用户')

#     try:
#         log = OperationLog(
#             user_id=user_id,
#             username=username,
#             operation_type=operation_type,      # 注意：字段名是 operation_type
#             resource_type=resource_type,
#             resource_id=resource_id,
#             resource_name=resource_name,
#             details=details,
#             ip_address=getattr(request, 'remote_addr', None),
#             user_agent=getattr(request, 'user_agent', {}).string if hasattr(request, 'user_agent') else None,
#             created_at=datetime.now(timezone.utc)
#         )
#         db.session.add(log)
#         db.session.commit()
#     except Exception as e:
#         db.session.rollback()
#         current_app.logger.error(f"记录操作日志失败: {e}")




from functools import wraps
from flask import request, current_app, jsonify, has_request_context
from flask_login import current_user
import jwt
from datetime import datetime, timezone
from extensions import db
from models.models import OperationLog, User

def admin_required(f):
    """要求管理员权限的装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401
        if not current_user.is_admin:
            return jsonify({'error': 'Admin privileges required'}), 403
        return f(*args, **kwargs)
    return decorated_function


def log_operation(operation_type, resource_type=None, resource_id=None, 
                  resource_name=None, details=None, user=None, user_id=None):
    """
    记录操作日志
    Args:
        operation_type: 操作类型 (如 'create', 'update', 'delete')
        resource_type: 资源类型 (如 'device', 'cabinet')
        resource_id: 资源ID
        resource_name: 资源名称
        details: 操作详情
        user: 可选的用户对象（优先使用）
        user_id: 可选的用户ID（当 user 不可用时使用）
    """
    # 确定用户信息
    final_user_id = None
    username = "系统"

    if user and hasattr(user, 'id'):
        final_user_id = user.id
        username = getattr(user, 'username', '未知用户')
    elif user_id:
        final_user_id = user_id
        try:
            user_obj = User.query.get(user_id)
            if user_obj:
                username = user_obj.username
        except:
            pass
    elif hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        final_user_id = current_user.id
        username = getattr(current_user, 'username', '未知用户')

    try:
        # 安全获取请求上下文信息
        ip_address = None
        user_agent = None
        
        if has_request_context():
            ip_address = request.remote_addr
            user_agent = request.user_agent.string if hasattr(request, 'user_agent') else None
        
        log = OperationLog(
            user_id=final_user_id,
            username=username,
            operation_type=operation_type,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        try:
            current_app.logger.error(f"记录操作日志失败: {e}")
        except:
            print(f"记录操作日志失败: {e}")