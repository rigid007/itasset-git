from datetime import datetime, timezone
import pytz


# def utc_to_local(value, tz_name='Asia/Shanghai'):
#     if not value:
#         return None
#     if isinstance(value, datetime):
#         utc_dt = value
#     elif isinstance(value, str):
#         try:
#             if 'T' in value:
#                 utc_dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
#             else:
#                 utc_dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
#         except (ValueError, TypeError):
#             return None
#     else:
#         return None
#     if utc_dt.tzinfo is None:
#         utc_dt = utc_dt.replace(tzinfo=timezone.utc)
#     beijing_tz = pytz.timezone(tz_name)
#     return utc_dt.astimezone(beijing_tz)


def format_bandwidth_filter(bandwidth):
    if not bandwidth:
        return "N/A"
    if bandwidth >= 1_000_000_000:
        return f"{bandwidth / 1_000_000_000:.2f} Gbps"
    if bandwidth >= 1_000_000:
        return f"{bandwidth / 1_000_000:.2f} Mbps"
    if bandwidth >= 1_000:
        return f"{bandwidth / 1_000:.2f} Kbps"
    return f"{bandwidth} bps"


def format_speed_filter(bps):
    if bps is None:
        return '-'
    if bps >= 1_000_000_000:
        return f"{bps / 1_000_000_000:.2f} Gbps"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    if bps >= 1_000:
        return f"{bps / 1_000:.2f} Kbps"
    return f"{bps:.0f} bps"


def format_bytes_filter(bytes_count):
    if not bytes_count:
        return "0 B"
    if bytes_count >= 1_099_511_627_776:
        return f"{bytes_count / 1_099_511_627_776:.2f} TB"
    if bytes_count >= 1_073_741_824:
        return f"{bytes_count / 1_073_741_824:.2f} GB"
    if bytes_count >= 1_048_576:
        return f"{bytes_count / 1_048_576:.2f} MB"
    if bytes_count >= 1_024:
        return f"{bytes_count / 1_024:.2f} KB"
    return f"{bytes_count} B"


def time_ago_filter(dt):
    if not dt:
        return '未知'
    now = datetime.utcnow()
    diff = now - dt
    seconds = diff.total_seconds()
    if seconds < 60:
        return '刚刚'
    if seconds < 3_600:
        return f'{int(seconds // 60)}分钟前'
    if seconds < 86_400:
        return f'{int(seconds // 3_600)}小时前'
    if seconds < 2_592_000:
        return f'{int(seconds // 86_400)}天前'
    if seconds < 31_536_000:
        return f'{int(seconds // 2_592_000)}个月前'
    return f'{int(seconds // 31_536_000)}年前'


def get_status_color(status):
    return {
        'online': 'success',
        'active': 'info',
        'inactive': 'secondary',
        'maintenance': 'warning',
        'offline': 'danger',
        'unknown': 'secondary'
    }.get((status or '').lower(), 'secondary')


def jinja2_enumerate(iterable, start=0):
    return enumerate(iterable, start)

# utils/template_filters.py



import pytz
from datetime import timezone, timedelta

def utc_to_local(value):
    if not value:
        return value

    beijing_tz = pytz.timezone('Asia/Shanghai')

    # ✅ 情况 1：已经有时区（极少数情况）
    if value.tzinfo is not None:
        return value.astimezone(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')

    # ✅ 情况 2（你现在 100% 命中这里）：
    # MySQL 已经偷偷 +8 了
    # 所以：先 -8 小时，还原成真实 UTC
    real_utc = value - timedelta(hours=8)
    real_utc = real_utc.replace(tzinfo=timezone.utc)

    # 再转成北京时间显示
    beijing_time = real_utc.astimezone(beijing_tz)
    return beijing_time.strftime('%Y-%m-%d %H:%M:%S')


def register_template_filters(app):
    app.jinja_env.filters['utc_to_local'] = utc_to_local
    app.jinja_env.filters['format_bandwidth'] = format_bandwidth_filter
    app.jinja_env.filters['format_speed'] = format_speed_filter
    app.jinja_env.filters['format_bytes'] = format_bytes_filter
    app.jinja_env.filters['time_ago'] = time_ago_filter
    app.jinja_env.filters['get_status_color'] = get_status_color
    app.jinja_env.filters['enumerate'] = jinja2_enumerate

