"""
Application factory and entry point.
"""
import os
import atexit
try:
    from dotenv import load_dotenv
    load_dotenv()  # 从 .env 加载环境变量（若存在），避免将密钥写入源码
except ImportError:
    pass

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import CSRFProtect

from extensions import db, login_manager, init_extensions
from models.models import User
from scheduler import configure_scheduler, shutdown_scheduler
from tasks.link_monitor import init_link_monitor
from app_init import init_database

# 1. 应用初始化
app = Flask(__name__)
app.config.from_object('config.Config')

# 2. 配置 CSRF
csrf = CSRFProtect(app)

# 3. 核心配置（统一由 config.Config 解析环境变量，避免两处逻辑漂移）
# SECRET_KEY / 数据库地址 / 引擎选项 / 上传限制等均在 config.py 中配置，
# 此处仅覆盖与本应用强相关的少量开关。
app.config['WTF_CSRF_ENABLED'] = True
app.config['TIMEZONE'] = 'Asia/Shanghai'

# 4. 模板全局变量
from utils.utils import get_device_status_color, get_device_color
from utils.permission import has_permission
app.jinja_env.globals['get_device_status_color'] = get_device_status_color
app.jinja_env.globals['get_device_color'] = get_device_color
app.jinja_env.globals['has_permission'] = has_permission

# 富文本安全过滤器（防止存储型 XSS）
from utils.html_sanitize import sanitize_html
app.jinja_env.filters['sanitize_html'] = sanitize_html

# 字典合并过滤器（供部分报表模板聚合使用）
def _jinja_merge(dict_a, dict_b):
    if not isinstance(dict_a, dict):
        dict_a = dict(dict_a) if dict_a is not None else {}
    result = dict(dict_a)
    result.update(dict_b)
    return result
app.jinja_env.filters['merge'] = _jinja_merge

# 5. 初始化扩展
try:
    init_extensions(app)
    print("扩展初始化成功")
except Exception as e:
    print(f"初始化扩展失败: {e}")
    import traceback
    traceback.print_exc()
    import sys
    sys.exit(1)

# 6. 登录管理配置
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# 7. 注册模板过滤器
from utils.template_filters import register_template_filters
register_template_filters(app)

# 8. 注册上下文处理器
from utils.context_processors import register_context_processors
register_context_processors(app)

# 9. 注册蓝图
from blueprints import register_blueprints
register_blueprints(app)

# 9.6 WebSSH / 实时终端（SocketIO）
from realtime import socketio
socketio.init_app(app, async_mode='threading')

# 9.5 全局登录守卫：除白名单外的所有路由都必须先登录，统一防止越权访问
# （原有逐路由 @login_required / @permission_required 继续生效，此处作为兜底防线）
PUBLIC_PATH_PREFIXES = ('/login', '/register', '/logout', '/static', '/about', '/health')


@app.before_request
def enforce_authentication():
    """未登录请求：白名单放行，其余 API/JSON 返回 401，浏览器请求重定向登录页。"""
    if request.path.startswith(PUBLIC_PATH_PREFIXES):
        return None
    if current_user.is_authenticated:
        return None
    wants_json = (request.path.startswith('/api')
                  or request.is_json
                  or request.headers.get('X-Requested-With') == 'XMLHttpRequest')
    if wants_json:
        return jsonify({'error': 'Authentication required'}), 401
    return redirect(url_for('auth.login'))

# 10. 日志配置
from utils.logging_config import setup_logging
setup_logging(app)

# 11. 错误处理
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

# 12. 活动日志显示
@app.route('/api/activities', methods=['GET'])
@login_required
def get_activities():
    """获取活动记录列表，支持分页和筛选"""
    from flask import request, jsonify
    from models.models import ActivityLog

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    type_filter = request.args.get('type')
    action_filter = request.args.get('action')
    user_filter = request.args.get('user')

    query = ActivityLog.query
    if type_filter:
        query = query.filter(ActivityLog.type == type_filter)
    if action_filter:
        query = query.filter(ActivityLog.action.like(f'%{action_filter}%'))
    if user_filter:
        query = query.filter(ActivityLog.user == user_filter)
    query = query.order_by(ActivityLog.timestamp.desc())

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    activities = []
    for log in paginated.items:
        activities.append({
            'timestamp': log.timestamp.isoformat() if log.timestamp else None,
            'type': log.type,
            'device_type': log.device_type,
            'name': log.name,
            'action': log.action,
            'status': log.status,
            'status_color': log.status_color,
            'user': log.user,
            'detail': log.detail,
        })

    return jsonify({
        'activities': activities,
        'total': paginated.total,
        'page': page,
        'per_page': per_page,
        'pages': paginated.pages
    })

# 13. 应用退出清理
@atexit.register
def cleanup():
    shutdown_scheduler()
    app.logger.info("应用退出，调度器已关闭")

# 14. 应用启动入口
if __name__ == '__main__':
    # 安全提醒：生产环境请使用 WSGI 服务器（如 waitress / gunicorn）部署，
    # 切勿使用 Flask 内置开发服务器，且不要开启 debug（存在远程代码执行风险）。
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    if debug_mode:
        print("WARNING: Flask 调试模式已开启，存在远程代码执行风险，请勿在生产环境启用。")
    host = os.environ.get('HOST', '127.0.0.1')  # 默认仅监听本机，避免暴露到全网
    port = int(os.environ.get('PORT', '5000'))

    init_database(app)
    init_link_monitor(app)
    configure_scheduler(app)

    app.logger.info("应用启动完成，开始监听请求")
    socketio.run(app, debug=debug_mode, host=host, port=port, allow_unsafe_werkzeug=True)
