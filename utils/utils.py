# utils.py
"""
Unified re-export shim.
Functions have been split into specialized modules:
  - utils/network_utils.py  (ping, IP, network functions)
  - utils/snmp_utils.py     (SNMP get/walk, device info, interface discovery)
  - utils/excel_utils.py    (Excel import/export)
All imports from utils.utils continue to work.
"""

import logging
from functools import wraps

from flask import current_app
from flask_login import current_user

from extensions import db

logger = logging.getLogger(__name__)

# ========== Re-exports from network_utils ==========
from utils.network_utils import (
    is_valid_ip, is_valid_mac, allowed_file,
    ping_device, ping_device_strict, ping_device_system,
    ping_device_socket, ping_device_tcp, batch_ping_devices,
    detect_device_reliable, calculate_checksum,
    parse_ip_range, scan_ip_range_worker, ip_range_import,
)

# ========== Re-exports from snmp_utils ==========
from utils.snmp_utils import (
    SNMP_TIMEOUT, SnmpClient, snmp_get, snmp_walk, walk_interfaces,
    snmp_get_device_info, scan_ip_with_snmp,
    OID_MAPPINGS, FALLBACK_OIDS,
    infer_device_type_from_snmp, update_device_snmp_info,
    snmp_discover_interfaces_real, save_discovered_interfaces,
    get_device_snmp_data, snmp_get_with_timeout, parse_if_status,
    normalize_mac, normalize_device_name,
    build_discovery_candidate, match_device_candidate,
    discover_lldp_neighbors, discover_cdp_neighbors,
    discover_arp_table, discover_fdb_table, discover_topology_summary,
)
from utils.vendor_oid_map import (
    identify_by_sys_object_id, known_brands, is_infra_agent,
    VENDOR_OID_PREFIXES,
)

# ========== Re-exports from excel_utils ==========
from utils.excel_utils import (
    generate_location_template, export_locations_to_excel,
    import_locations_from_excel, export_devices_to_excel,
    generate_device_template, import_devices_from_excel,
)

# ========== Functions that remain in utils.py ==========

def with_app_context(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        with current_app.app_context():
            return f(*args, **kwargs)
    return wrapper


def get_device_status_color(status):
    status_colors = {'online': 'success', 'offline': 'danger', 'fault': 'warning', 'unknown': 'secondary'}
    return status_colors.get(status, 'secondary')


def get_device_color(device_type, variant='light'):
    colors = {
        'router':    {'light': '#28a745', 'dark': '#1e7e34'},
        'switch':    {'light': '#007bff', 'dark': '#0056b3'},
        'server':    {'light': '#6610f2', 'dark': '#4a0fc2'},
        'storage':   {'light': '#e83e8c', 'dark': '#c2185b'},
        'firewall':  {'light': '#fd7e14', 'dark': '#e65100'},
        'ap':       {'light': '#17a2b8', 'dark': '#117a8b'},
        'other':     {'light': '#6c757d', 'dark': '#495057'},
    }
    return colors.get(device_type or 'other', colors['other']).get(variant, '#6c757d')

def send_dingtalk(webhook_url, message):
    """钉钉机器人消息推送"""
    import requests
    data = {"msgtype": "text", "text": {"content": message}}
    requests.post(webhook_url, json=data)


def log_activity(type, name, action, status='成功', status_color='success',
                 user=None, detail='', device_type=None):
    """写入活动日志"""
    from models.models import ActivityLog

    try:
        if not user and hasattr(current_user, 'username'):
            user = current_user.username
        else:
            user = user or '系统'
    except Exception:
        user = user or '系统'

    log = ActivityLog(
        type=type,
        device_type=device_type if type == 'device' else None,
        name=name,
        action=action,
        status=status,
        status_color=status_color,
        user=user,
        detail=detail
    )
    db.session.add(log)
    db.session.commit()
