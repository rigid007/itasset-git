# -*- coding: utf-8 -*-
"""
PyInstaller 打包入口（launcher）。

非打包环境（python run_app.py）也能直接跑，等价于 wsgi.py 的 waitress 启动方式，
便于本地验证。打包后由 PyInstaller 把本项目所有模块 + templates/static/uploads
一并冻结，运行时把"可写数据"（数据库、上传、日志）重定向到 exe 同级目录，
并自动打开浏览器。

关键修正：
  config.py 用 os.path.dirname(__file__) 计算 BASE_DIR（指向打包临时目录 _MEIPASS），
  数据库/上传会落到不可持久的位置。这里在首次 db 访问前覆盖 app.config 里的可写路径，
  不改源码即可让 SQLite / 上传落到 exe 同目录，保证数据持久。
"""
import os
import sys
import webbrowser
import threading

FROZEN = getattr(sys, 'frozen', False)


def _setup_frozen_paths():
    """打包环境下，把可写数据目录重定向到 exe 同级目录，并持久化 SECRET_KEY。"""
    base = os.path.dirname(sys.executable)
    os.chdir(base)

    # 持久化 SECRET_KEY，避免每次重启生成随机 key 导致已登录会话失效
    env_path = os.path.join(base, '.env')
    if not os.path.exists(env_path):
        try:
            import secrets
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write('SECRET_KEY=' + secrets.token_hex(32) + '\n')
        except Exception:
            pass
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    return base


if FROZEN:
    BASE = _setup_frozen_paths()
else:
    BASE = os.path.abspath(os.path.dirname(__file__))


# 先构建 Flask app（会触发所有蓝图/扩展的静态导入）
from app import app as application

# 覆盖可写路径（必须在任何 db 访问之前）
if FROZEN:
    os.makedirs(os.path.join(BASE, 'instance'), exist_ok=True)
    os.makedirs(os.path.join(BASE, 'uploads'), exist_ok=True)
    os.makedirs(os.path.join(BASE, 'logs'), exist_ok=True)
    application.config['SQLALCHEMY_DATABASE_URI'] = \
        'sqlite:///' + os.path.join(BASE, 'instance', 'asset.db')
    application.config['UPLOAD_FOLDER'] = os.path.join(BASE, 'uploads')


import logging
logger = logging.getLogger('run_app')


def _enabled(name, default='1'):
    return os.environ.get(name, default).lower() in ('1', 'true', 'yes', 'on')


def bootstrap(app):
    """等同于 wsgi.bootstrap：建表 / 链路监控 / 调度器（不触发 wsgi 模块级副作用）。"""
    from app_init import init_database
    from scheduler import configure_scheduler
    from tasks.link_monitor import init_link_monitor

    try:
        init_database(app)
        logger.info('数据库初始化完成')
    except Exception as e:
        logger.error('数据库初始化失败: %s', e)
        raise

    if _enabled('ENABLE_LINK_MONITOR'):
        try:
            init_link_monitor(app)
            logger.info('链路监控初始化完成')
        except Exception as e:
            logger.error('链路监控初始化失败: %s', e)
    else:
        logger.info('ENABLE_LINK_MONITOR=0，跳过链路监控初始化')

    if _enabled('ENABLE_SCHEDULER'):
        try:
            configure_scheduler(app)
            logger.info('定时任务调度器已启动')
        except Exception as e:
            logger.error('调度器启动失败: %s', e)
    else:
        logger.info('ENABLE_SCHEDULER=0，本进程不启动定时任务')
    return app


def main():
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8000'))
    url = 'http://{host}:{port}'.format(host=host, port=port)

    print('=' * 60)
    print(' IT 资产与运维管理平台 (PyInstaller build)')
    print(' 地址: ' + url)
    print('=' * 60)
    print('正在初始化数据库与定时任务...')

    bootstrap(application)

    # 延迟打开浏览器
    threading.Timer(2.0, lambda: _open_browser(url)).start()

    from waitress import serve
    print('服务已启动，按 Ctrl+C 退出。')
    serve(application, host=host, port=port, threads=16)


def _open_browser(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == '__main__':
    main()
