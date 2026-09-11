# services/__init__.py
"""服务层 - 提供统一的业务逻辑入口。"""

from services.device_service import (
    find_device,
    find_or_create_device,
    find_device_by_any,
    update_device_info,
    normalize_mac,
    format_mac_display,
    merge_duplicate_devices,
    merge_devices_by_ip_mac,
)
from services.device_group_service import (
    classify_single_device,
    remove_device_from_group,
    auto_classify_by_ip_subnet,
    auto_classify_by_name_pattern,
    get_group_tree,
    get_all_groups_flat,
)
from services.notification_service import (
    init_alert_settings,
    get_alert_settings,
    save_alert_settings,
    send_email,
    send_wechat,
    send_slack,
    send_dingtalk,
    send_feishu,
    send_webhook,
    send_notification,
)
from services.event_monitor import EventMonitor, start_event_monitor
from services.escalation_service import run_escalations

__all__ = [
    'find_device', 'find_or_create_device', 'find_device_by_any',
    'update_device_info', 'normalize_mac', 'format_mac_display',
    'merge_duplicate_devices', 'merge_devices_by_ip_mac',
    'classify_single_device', 'remove_device_from_group',
    'auto_classify_by_ip_subnet', 'auto_classify_by_name_pattern',
    'get_group_tree', 'get_all_groups_flat',
    'init_alert_settings', 'get_alert_settings', 'save_alert_settings',
    'send_email', 'send_wechat', 'send_slack', 'send_dingtalk', 'send_feishu',
    'send_webhook',
    'send_notification',
    'EventMonitor', 'start_event_monitor',
    'run_escalations',
]
