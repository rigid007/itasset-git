# -*- coding: utf-8 -*-
"""应用配置：从 .env / 环境变量统一解析，避免在源码中硬编码数据库密码等敏感信息。"""
import os
import secrets
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # SECRET_KEY：必须来自环境变量；未设置时生成随机值（仅开发/演示用，重启失效）。
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    # 获取当前文件（config.py）所在目录的绝对路径
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    # 指向 instance 子目录下的 asset.db
    # SQLALCHEMY_DATABASE_URI = f'sqlite:///{os.path.join(BASE_DIR, "instance", "asset.db")}'
    # 数据库地址：优先使用 DATABASE_URL 环境变量；否则由 DB_* 环境变量拼接。
    # 严禁在源代码中硬编码数据库密码。
    _db_password = os.environ.get('DB_PASSWORD', '')
    if os.environ.get('DATABASE_URL'):
        SQLALCHEMY_DATABASE_URI = os.environ['DATABASE_URL']
    elif _db_password:
        SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://{user}:{pw}@{host}:{port}/{name}'.format(
            user=os.environ.get('DB_USER', 'root'),
            pw=_db_password,
            host=os.environ.get('DB_HOST', 'localhost'),
            port=os.environ.get('DB_PORT', '3306'),
            name=os.environ.get('DB_NAME', 'asset'),
        )
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'asset.db')

    # 根据数据库类型设置不同的引擎选项
    if SQLALCHEMY_DATABASE_URI.startswith('sqlite'):
        SQLALCHEMY_ENGINE_OPTIONS = {
            'connect_args': {'check_same_thread': False}
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_size': 20,
            'max_overflow': 30,
            'pool_timeout': 60,
            'pool_pre_ping': True,
            'pool_recycle': 280,
        }
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=60)

    # 是否允许公开自助注册（内部资产系统建议设为 false，由管理员统一开通账号）
    ALLOW_PUBLIC_REGISTRATION = os.environ.get('ALLOW_PUBLIC_REGISTRATION', 'true').lower() in ('1', 'true', 'yes')

    # SNMP 默认配置
    SNMP_DEFAULT_COMMUNITY = 'public'
    SNMP_DEFAULT_TIMEOUT = 2
    SNMP_DEFAULT_RETRIES = 1

    # 以下 Redis 配置已保留兼容占位，接口采集已改为直接写入 InterfaceMonitorData，
    # 当前代码不再依赖 Redis/Memurai。后续如新增队列消费者，再重新启用即可。
    REDIS_HOST = 'localhost'
    REDIS_PORT = 6379
    REDIS_DB = 0
    REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', '')
    REDIS_USERNAME = None
    REDIS_QUEUE_KEY = 'interface_monitor:queue'

    # 设备状态检查配置
    PING_TIMEOUT = 2
    PING_COUNT = 2

    # 事件驱动监控（SNMP Trap / Syslog / JSON 心跳）配置
    # 默认开启；使用非特权端口，避免需要 root 绑定 162/514。
    # 真实 SNMP Trap 来自网络设备的 UDP 162，需在设备侧用 snmptrapd 转发到 trap_port。
    EVENT_MONITOR_ENABLED = os.environ.get('EVENT_MONITOR_ENABLED', '1') == '1'
    EVENT_MONITOR_TRAP_PORT = int(os.environ.get('EVENT_MONITOR_TRAP_PORT', '9162'))
    EVENT_MONITOR_SYSLOG_PORT = int(os.environ.get('EVENT_MONITOR_SYSLOG_PORT', '9514'))

    # 分页配置
    ITEMS_PER_PAGE = 20

    # 拓扑配置
    TOPOLOGY_IMAGE_FORMAT = 'png'
    TOPOLOGY_DPI = 100

    # 带外管理（OOB）：iDRAC / iLO / iBMC / XCC 配置
    OOB_ENABLED = os.environ.get('OOB_ENABLED', '1') == '1'
    OOB_POLL_INTERVAL_SEC = int(os.environ.get('OOB_POLL_INTERVAL_SEC', '300'))
    OOB_POLL_WORKERS = int(os.environ.get('OOB_POLL_WORKERS', '8'))
    OOB_TIMEOUT = int(os.environ.get('OOB_TIMEOUT', '10'))
    OOB_VERIFY_SSL = os.environ.get('OOB_VERIFY_SSL', '0') == '1'
    OOB_SENSOR_ALERT_WINDOW_MINUTES = int(os.environ.get('OOB_SENSOR_ALERT_WINDOW_MINUTES', '15'))
    OOB_SENSOR_ALERT_STRIKES = int(os.environ.get('OOB_SENSOR_ALERT_STRIKES', '2'))
    OOB_SENSOR_NOTIFY_RECOVERY = os.environ.get('OOB_SENSOR_NOTIFY_RECOVERY', '1') == '1'

    # NetFlow 流量采集配置（新增，参考 DCOS 平台 netflow 模块）
    NETFLOW_ENABLED = os.environ.get('NETFLOW_ENABLED', '1') == '1'
    NETFLOW_RETENTION_DAYS = int(os.environ.get('NETFLOW_RETENTION_DAYS', '30'))
    NETFLOW_BUFFER_FLUSH_SEC = int(os.environ.get('NETFLOW_BUFFER_FLUSH_SEC', '10'))
    NETFLOW_ALERT_THRESHOLD_MBPS = float(os.environ.get('NETFLOW_ALERT_THRESHOLD_MBPS', '0'))
    NETFLOW_ALERT_SEVERITY = os.environ.get('NETFLOW_ALERT_SEVERITY', 'warning')
    # 内网网段列表（逗号分隔 CIDR），用于“对外网段 Top 会话”判断
    NETFLOW_INTERNAL_SUBNETS = os.environ.get('NETFLOW_INTERNAL_SUBNETS', '10.0.0.0/8,172.16.0.0/12,192.168.0.0/16')
