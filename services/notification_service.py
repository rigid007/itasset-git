"""
notification_service.py - 告警通知发送服务
支持: Email(SMTP) / 企业微信(机器人Webhook) / Slack / 通用Webhook
"""
import json
import logging
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# ==================== 全局告警设置 (SystemConfig) ====================

ALERT_SETTINGS_KEYS = {
    # SMTP
    'smtp_server': {'category': 'alert', 'default': '', 'description': 'SMTP服务器地址'},
    'smtp_port': {'category': 'alert', 'default': '587', 'description': 'SMTP端口'},
    'smtp_use_tls': {'category': 'alert', 'default': 'true', 'description': '使用TLS'},
    'smtp_user': {'category': 'alert', 'default': '', 'description': 'SMTP用户名'},
    'smtp_password': {'category': 'alert', 'default': '', 'description': 'SMTP密码'},
    'smtp_from_addr': {'category': 'alert', 'default': '', 'description': '发件人地址'},
    'smtp_from_name': {'category': 'alert', 'default': '告警系统', 'description': '发件人名称'},
    # 企业微信
    'wechat_webhook_url': {'category': 'alert', 'default': '', 'description': '企业微信机器人Webhook URL'},
    'wechat_proxy': {'category': 'alert', 'default': '', 'description': '企业微信代理(可选)'},
    # Slack
    'slack_webhook_url': {'category': 'alert', 'default': '', 'description': 'Slack Webhook URL'},
    # 通用
    'webhook_default_url': {'category': 'alert', 'default': '', 'description': '默认Webhook URL'},
    'webhook_default_headers': {'category': 'alert', 'default': '{}', 'description': '默认Webhook请求头(JSON)'},
}


def init_alert_settings():
    """初始化默认告警设置到数据库"""
    from extensions import db
    from models.settings_models import SystemConfig
    for key, meta in ALERT_SETTINGS_KEYS.items():
        existing = SystemConfig.query.filter_by(key=key).first()
        if not existing:
            s = SystemConfig(
                key=key,
                value=meta['default'],
                description=meta['description'],
                category=meta['category'],
                is_public=False,
            )
            db.session.add(s)
    db.session.commit()


def get_alert_settings():
    """读取所有告警设置"""
    from models.settings_models import SystemConfig
    settings = {}
    for key in ALERT_SETTINGS_KEYS:
        record = SystemConfig.query.filter_by(key=key).first()
        if record:
            settings[key] = record.value
        else:
            settings[key] = ALERT_SETTINGS_KEYS[key]['default']
    return settings


def save_alert_settings(settings_dict):
    """保存告警设置"""
    from extensions import db
    from models.settings_models import SystemConfig
    for key, value in settings_dict.items():
        if key in ALERT_SETTINGS_KEYS:
            record = SystemConfig.query.filter_by(key=key).first()
            if record:
                record.value = str(value)
            else:
                meta = ALERT_SETTINGS_KEYS[key]
                record = SystemConfig(
                    key=key, value=str(value),
                    description=meta['description'],
                    category=meta['category'],
                    is_public=False,
                )
                db.session.add(record)
    db.session.commit()


# ==================== Email 发送 ====================

def send_email(recipients, subject, body, config=None):
    """通过SMTP发送邮件

    Args:
        recipients: 收件人列表或逗号分隔的字符串
        subject: 邮件主题
        body: 邮件正文(HTML)
        config: SMTP配置字典，为空时从系统设置读取

    Returns:
        (success: bool, message: str)
    """
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.replace(';', ',').split(',') if r.strip()]
    if not recipients:
        return False, '收件人列表为空'

    # 从config或全局设置获取SMTP参数
    if config:
        smtp_config = config
    else:
        smtp_config = get_alert_settings()

    server = smtp_config.get('smtp_server', '')
    port = int(smtp_config.get('smtp_port', 587))
    use_tls = str(smtp_config.get('smtp_use_tls', 'true')).lower() == 'true'
    user = smtp_config.get('smtp_user', '')
    password = smtp_config.get('smtp_password', '')
    from_addr = smtp_config.get('smtp_from_addr', user)
    from_name = smtp_config.get('smtp_from_name', '告警系统')

    if not server:
        return False, 'SMTP服务器未配置'
    if not user or not password:
        return False, 'SMTP用户名或密码未配置'

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = f'{from_name} <{from_addr}>'
        msg['To'] = ', '.join(recipients)

        part = MIMEText(body, 'html', 'utf-8')
        msg.attach(part)

        if use_tls:
            smtp = smtplib.SMTP(server, port, timeout=15)
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
        else:
            smtp = smtplib.SMTP(server, port, timeout=15)

        if user:
            smtp.login(user, password)

        smtp.sendmail(from_addr, recipients, msg.as_string())
        smtp.quit()

        logger.info(f'邮件发送成功 -> {recipients}')
        return True, f'邮件已发送到 {", ".join(recipients)}'

    except smtplib.SMTPAuthenticationError:
        return False, 'SMTP认证失败，请检查用户名和密码'
    except smtplib.SMTPConnectError:
        return False, f'无法连接到SMTP服务器 {server}:{port}'
    except smtplib.SMTPRecipientsRefused:
        return False, '收件人被服务器拒绝'
    except smtplib.SMTPServerDisconnected:
        return False, 'SMTP服务器连接断开'
    except Exception as e:
        logger.exception(f'邮件发送失败: {e}')
        return False, f'邮件发送失败: {str(e)}'


# ==================== 企业微信 发送 ====================

def send_wechat(recipients, title, content, config=None):
    """通过企业微信机器人Webhook发送消息

    Args:
        recipients: 接收人/群聊列表(Webhook中已配置)
        title: 消息标题
        content: 消息内容(支持Markdown)
        config: 包含 wechat_webhook_url, wechat_proxy

    Returns:
        (success: bool, message: str)
    """
    if config:
        webhook_url = config.get('wechat_webhook_url', '')
        proxy = config.get('wechat_proxy', '')
    else:
        settings = get_alert_settings()
        webhook_url = settings.get('wechat_webhook_url', '')
        proxy = settings.get('wechat_proxy', '')

    if not webhook_url:
        return False, '企业微信Webhook URL未配置'

    try:
        markdown_content = f'## {title}\n{content}'
        payload = {
            'msgtype': 'markdown',
            'markdown': {'content': markdown_content},
        }

        proxies = {'https': proxy} if proxy else None
        resp = requests.post(
            webhook_url, json=payload, proxies=proxies,
            timeout=15, headers={'Content-Type': 'application/json'},
        )

        if resp.status_code == 200:
            result = resp.json()
            if result.get('errcode') == 0:
                return True, '企业微信消息已发送'
            else:
                return False, f'企业微信API错误: {result.get("errmsg", "未知错误")}'
        else:
            return False, f'企业微信请求失败, HTTP {resp.status_code}'

    except requests.Timeout:
        return False, '企业微信请求超时'
    except requests.ConnectionError:
        return False, '无法连接到企业微信服务器'
    except Exception as e:
        logger.exception(f'企业微信发送失败: {e}')
        return False, f'企业微信发送失败: {str(e)}'


# ==================== Slack 发送 ====================

def send_slack(recipients, channel, message, config=None):
    """通过Slack Webhook发送消息

    Args:
        recipients: 接收者列表(webhook_url优先)
        channel: Slack频道
        message: 消息内容

    Returns:
        (success: bool, message: str)
    """
    if config:
        webhook_url = config.get('slack_webhook_url', '')
    else:
        settings = get_alert_settings()
        webhook_url = settings.get('slack_webhook_url', '')

    # 如果config中没有，尝试从recipients获取
    if not webhook_url and recipients:
        if isinstance(recipients, list) and recipients:
            webhook_url = recipients[0]
        elif isinstance(recipients, str):
            webhook_url = recipients

    if not webhook_url:
        return False, 'Slack Webhook URL未配置'

    try:
        payload = {'text': message}
        if channel:
            payload['channel'] = channel

        resp = requests.post(
            webhook_url, json=payload,
            timeout=15, headers={'Content-Type': 'application/json'},
        )

        if resp.status_code == 200:
            return True, 'Slack消息已发送'
        else:
            return False, f'Slack请求失败, HTTP {resp.status_code}'

    except requests.Timeout:
        return False, 'Slack请求超时'
    except requests.ConnectionError:
        return False, '无法连接到Slack服务器'
    except Exception as e:
        logger.exception(f'Slack发送失败: {e}')
        return False, f'Slack发送失败: {str(e)}'


# ==================== Webhook 发送 ====================

def send_webhook(recipients, data, headers=None, config=None):
    """发送通用Webhook

    Args:
        recipients: URL列表或URL字符串
        data: 发送的数据(dict或str)
        headers: HTTP头字典
        config: 额外配置

    Returns:
        (success: bool, message: str)
    """
    url = ''
    if isinstance(recipients, list) and recipients:
        url = recipients[0]
    elif isinstance(recipients, str):
        url = recipients

    if not url:
        settings = get_alert_settings()
        url = settings.get('webhook_default_url', '')

    if not url:
        return False, 'Webhook URL未配置'

    if headers is None:
        headers = {}
    if not headers.get('Content-Type'):
        headers['Content-Type'] = 'application/json'

    try:
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                pass

        resp = requests.post(
            url, json=data if isinstance(data, dict) else data,
            headers=headers, timeout=15,
        )

        if 200 <= resp.status_code < 300:
            return True, f'Webhook已发送 (HTTP {resp.status_code})'
        else:
            return False, f'Webhook返回错误 (HTTP {resp.status_code}): {resp.text[:200]}'

    except requests.Timeout:
        return False, 'Webhook请求超时'
    except requests.ConnectionError:
        return False, f'无法连接到 {url}'
    except Exception as e:
        logger.exception(f'Webhook发送失败: {e}')
        return False, f'Webhook发送失败: {str(e)}'


# ==================== 统一发送入口 ====================

def send_notification(notification_config, title=None, content=None):
    """统一通知发送入口

    Args:
        notification_config: NotificationConfig ORM 对象
        title: 标题(覆盖模板)
        content: 内容(覆盖模板)

    Returns:
        (success: bool, message: str)
    """
    if not notification_config or not notification_config.enabled:
        return False, '通知配置已禁用或不存在'

    # 使用配置中的模板或传入的标题/内容
    message_title = title or notification_config.title_template or '【告警通知】'
    message_content = content or notification_config.message_template or ''

    receivers = notification_config.get_receivers() or []
    extra_config = notification_config.get_config() or {}

    ntype = notification_config.notification_type

    if ntype == 'email':
        return send_email(receivers, message_title, message_content, extra_config)
    elif ntype == 'wechat':
        return send_wechat(receivers, message_title, message_content, extra_config)
    elif ntype == 'slack':
        channel = extra_config.get('channel', '')
        return send_slack(receivers, channel, message_content, extra_config)
    elif ntype == 'webhook':
        headers = extra_config.get('headers', {})
        return send_webhook(receivers, message_content, headers, extra_config)
    elif ntype == 'sms':
        # SMS暂不实现，后续可集成第三方短信API
        return False, '短信发送暂未实现，请使用邮件或Webhook'
    else:
        return False, f'不支持的通知类型: {ntype}'
