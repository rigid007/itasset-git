# utils/email.py
"""邮件通知 - 统一委托给 services.notification_service（SMTP 配置读取系统设置）。"""

from services.notification_service import send_email as _send_email


def send_email(subject, recipients, text_body, html_body=None):
    """发送邮件（兼容旧签名 subject/recipients/text_body/html_body）。

    实际发送逻辑统一走 notification_service.send_email，避免维护多份 SMTP 实现。
    返回 (success, message)。
    """
    body = html_body if html_body is not None else text_body
    return _send_email(recipients, subject, body)


def send_approval_notification(request_obj):
    """发送审批结果通知给申请人"""
    requester_email = request_obj.requester.email if request_obj.requester else None
    if not requester_email:
        return

    subject = f'备件申请审批结果 - {request_obj.request_number}'
    text_body = f"""
    您的备件申请 {request_obj.request_number} 已完成审批。
    审批结果：{request_obj.approval_status}
    审批意见：{request_obj.approval_notes or '无'}
    审批人：{request_obj.approved_by}
    审批时间：{request_obj.approved_at.strftime('%Y-%m-%d %H:%M')}
    """
    return send_email(subject, [requester_email], text_body)


def send_new_request_notification(request_obj):
    """新申请通知所有管理员"""
    from models import User
    admins = User.query.filter(User.role == 'admin').all()
    admin_emails = [admin.email for admin in admins if admin.email]

    subject = f'新的备件申请 - {request_obj.request_number}'
    text_body = f"""
    有新的备件申请需要审批：
    申请单号：{request_obj.request_number}
    申请人：{request_obj.requester_name}
    部门：{request_obj.department}
    备件：{request_obj.spare_part.name}
    数量：{request_obj.quantity}
    紧急程度：{request_obj.urgency}
    申请原因：{request_obj.reason}
    申请时间：{request_obj.requested_at.strftime('%Y-%m-%d %H:%M')}
    请登录系统处理。
    """
    return send_email(subject, admin_emails, text_body)
