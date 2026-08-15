"""审计日志工具 - 共享 log_audit() 函数"""
import json
from flask import request
from flask_login import current_user
from extensions import db


def log_audit(action, resource_type, resource_id, message, details=None, changes=None, status='success', user_id=None):
    """记录审计日志到 audit_logs 表"""
    # 延迟导入避免循环引用
    from models.config_models import AuditLog

    try:
        uid = user_id
        if uid is None and current_user.is_authenticated:
            uid = current_user.id

        audit_log = AuditLog(
            user_id=uid,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            message=message,
            details=json.dumps(details, ensure_ascii=False) if details else None,
            changes=json.dumps(changes, ensure_ascii=False) if changes else None,
            status=status,
            ip_address=request.remote_addr if request else None,
            user_agent=request.user_agent.string if request and request.user_agent else None,
            request_method=request.method if request else None,
            request_path=request.path if request else None,
        )
        db.session.add(audit_log)
        db.session.commit()
        return True
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"审计日志记录失败: {str(e)}")
        db.session.rollback()
        return False
