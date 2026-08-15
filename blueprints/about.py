# about.py - 关于蓝图

from flask import Blueprint, render_template, send_from_directory, current_app, jsonify
import os
import time
import platform

from utils.audit import log_audit

about_bp = Blueprint('about', __name__, url_prefix='/about')

# 应用进程启动时间戳（蓝图模块加载时记录，约等于进程启动时刻）
_APP_START_TIME = time.time()

# 产品信息集中维护，供页面与 /api/version 复用
PRODUCT = {
    'name': 'IT资产与运维管理平台',
    'short_name': 'ITAM',
    'full_name': 'IT资产与运维管理平台',
    'version': '2.1.0',
    'edition': '企业版',
    'build_date': '2026-07-27',
    'support': 'admin@example.com',
    'copyright': '网络资产管理系统',
}


def _format_uptime(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f'{d} 天')
    if d or h:
        parts.append(f'{h} 小时')
    parts.append(f'{m} 分')
    return ' '.join(parts)


def _safe_count(query):
    """安全计数：出错（如表不存在）时返回占位符，保证页面仍可渲染。"""
    try:
        return query.count()
    except Exception:
        return '—'


@about_bp.route('/user_manual')
def user_manual():
    """使用手册"""
    return render_template('about/user_manual.html')


@about_bp.route('/system_about')
def system_about():
    """关于系统 —— 丰富后的系统信息页"""
    import sqlalchemy
    from sqlalchemy import text
    from extensions import db

    # 运行环境版本信息
    try:
        import pkg_resources
        flask_version = pkg_resources.get_distribution('Flask').version
    except Exception:
        flask_version = '未知'
    try:
        sqlalchemy_version = sqlalchemy.__version__
    except Exception:
        sqlalchemy_version = '未知'

    # 数据库后端与连接状态
    db_backend = '未知'
    db_status = '未知'
    try:
        db_backend = db.engine.dialect.name
        db.session.execute(text('SELECT 1'))
        db_status = '正常'
    except Exception:
        db_status = '异常'

    # 启动时间 / 运行时长
    start_dt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_APP_START_TIME))
    uptime = _format_uptime(time.time() - _APP_START_TIME)

    # 系统数据概览（实时计数）
    stats = {}
    try:
        from models.models import Device, Location, Cabinet, User, Interface, Alert
        from models.maintenance_models import WorkOrder, ChangeRequest, ServiceCatalog
        stats = {
            'devices': _safe_count(Device.query),
            'locations': _safe_count(Location.query),
            'cabinets': _safe_count(Cabinet.query),
            'interfaces': _safe_count(Interface.query),
            'users': _safe_count(User.query),
            'alerts': _safe_count(Alert.query),
            'work_orders': _safe_count(WorkOrder.query),
            'changes': _safe_count(ChangeRequest.query),
            'services': _safe_count(ServiceCatalog.query),
        }
    except Exception:
        stats = {}

    system_info = {
        'os_name': platform.system(),
        'os_version': platform.version(),
        'os_machine': platform.machine(),
        'hostname': platform.node(),
        'python_version': platform.python_version(),
        'flask_version': flask_version,
        'sqlalchemy_version': sqlalchemy_version,
        'db_backend': db_backend,
        'db_status': db_status,
        'debug': bool(current_app.debug),
        'env': getattr(current_app, 'env', None) or os.environ.get('FLASK_ENV', 'production'),
        'start_time': start_dt,
        'uptime': uptime,
        'now': time.strftime('%Y-%m-%d %H:%M:%S'),
    }

    return render_template('about/system_about.html',
                           product=PRODUCT,
                           system_info=system_info,
                           overview=stats)


@about_bp.route('/download/manual')
def download_manual():
    """下载使用手册"""
    manual_path = os.path.join(current_app.root_path, 'static', 'docs')
    return send_from_directory(manual_path, 'user_manual.pdf', as_attachment=True)


@about_bp.route('/api/version')
def api_version():
    """API版本信息"""
    return jsonify({
        'application': PRODUCT['full_name'],
        'short_name': PRODUCT['short_name'],
        'version': PRODUCT['version'],
        'edition': PRODUCT['edition'],
        'build_date': PRODUCT['build_date'],
        'api_version': 'v1',
        'support': PRODUCT['support'],
    })
