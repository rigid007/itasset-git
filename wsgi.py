#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WSGI 生产入口

背景
----
`app.py` 里的 `init_database()` / `init_link_monitor()` / `configure_scheduler()`
都写在 `if __name__ == '__main__':` 分支内，只有用 `python app.py` 直接运行才会执行。
如果生产上用 waitress / gunicorn 指向 `app:app`，**这三项初始化都不会执行**，
后果是：所有定时任务（设备检测、链路监控、SLA 计算、可用率采集、日志清理…）全部不运行。

本文件提供一个正确的 WSGI 入口，把这三项初始化补齐。

用法
----
    # waitress (Windows 推荐)
    waitress-serve --host=0.0.0.0 --port=8000 wsgi:application

    # gunicorn (Linux)
    gunicorn -w 4 -b 0.0.0.0:8000 wsgi:application

多进程部署注意事项
------------------
APScheduler 是**进程内**调度器。若以多 worker 运行（如 `gunicorn -w 4`），
每个 worker 都会启动一份调度器，导致定时任务被重复执行 4 次。

正确做法二选一：
  1) 只让一个进程跑调度器：其余 worker 设置环境变量 `ENABLE_SCHEDULER=0`；
     或单独起一个 `ENABLE_SCHEDULER=1` 的常驻进程专跑调度，Web 进程全部设为 0。
  2) 单 worker 多线程：`waitress-serve --threads=16`（Windows 下的推荐方案），
     此时只有一个进程，不存在重复调度问题。

环境变量
--------
  ENABLE_SCHEDULER   1(默认)=启动定时任务  0=不启动（供多 worker 场景关闭）
  ENABLE_LINK_MONITOR 1(默认)=初始化链路监控实例  0=不初始化
"""
import os
import logging

from app import app as application  # noqa: F401  Flask 应用实例
from app_init import init_database
from scheduler import configure_scheduler
from tasks.link_monitor import init_link_monitor

logger = logging.getLogger(__name__)


def _enabled(name, default='1'):
    return os.environ.get(name, default).lower() in ('1', 'true', 'yes', 'on')


def bootstrap(app):
    """执行 app.py 的 __main__ 分支里那套初始化"""
    # 1) 建表 / 初始化基础数据
    try:
        init_database(app)
        logger.info('[wsgi] 数据库初始化完成')
    except Exception as e:
        logger.error(f'[wsgi] 数据库初始化失败: {e}')
        raise

    # 2) 链路监控实例（供调度任务复用，避免每次调度新建线程池）
    if _enabled('ENABLE_LINK_MONITOR'):
        try:
            init_link_monitor(app)
            logger.info('[wsgi] 链路监控初始化完成')
        except Exception as e:
            logger.error(f'[wsgi] 链路监控初始化失败: {e}')
    else:
        logger.info('[wsgi] ENABLE_LINK_MONITOR=0，跳过链路监控初始化')

    # 3) 定时任务调度器
    if _enabled('ENABLE_SCHEDULER'):
        try:
            configure_scheduler(app)
            logger.info('[wsgi] 定时任务调度器已启动')
        except Exception as e:
            logger.error(f'[wsgi] 调度器启动失败: {e}')
    else:
        logger.info('[wsgi] ENABLE_SCHEDULER=0，本进程不启动定时任务')

    return app


bootstrap(application)

# SocketIO（WebSSH 实时终端）已在 app.py 中通过 init_app 挂载到 app.wsgi_app，
# waitress 等 WSGI 服务器直接服务 application 即可同时处理 /socket.io 请求。
try:
    from realtime import socketio  # noqa: F401  确保实例已初始化
    logger.info('[wsgi] SocketIO 已挂载（WebSSH 可用）')
except Exception as e:
    logger.error(f'[wsgi] SocketIO 初始化失败: {e}')

# 兼容 `gunicorn wsgi:app` 这种写法
app = application


if __name__ == '__main__':
    # 便于本地用 waitress 直接起：python wsgi.py
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8000'))
    try:
        from waitress import serve
        print(f'waitress serving on http://{host}:{port}')
        serve(application, host=host, port=port, threads=16)
    except ImportError:
        print('未安装 waitress，回退到 Flask 开发服务器（请勿用于生产）')
        application.run(host=host, port=port)
