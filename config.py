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

    # 是否允许公开自助注册（内部资产系统建议设为 false，由管理员统一开通账户）
    ALLOW_PUBLIC_REGISTRATION = os.environ.get('ALLOW_PUBLIC_REGISTRATION', 'true').lower() in ('1', 'true', 'yes')
    
    # SNMP默认配置
    SNMP_DEFAULT_COMMUNITY = 'public'
    SNMP_DEFAULT_TIMEOUT = 2
    SNMP_DEFAULT_RETRIES = 1

    REDIS_HOST = 'localhost'          # Memurai 服务器地址
    REDIS_PORT = 6379                 # Memurai 端口
    REDIS_DB = 0                      # 使用的数据库编号（0-15）
    REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', '')  # 生产环境请通过环境变量设置强密码，切勿硬编码
    REDIS_USERNAME = None              # 如果启用了 ACL 并创建了用户，填写用户名；否则 None
    REDIS_QUEUE_KEY = 'interface_monitor:queue'  # 队列名称
    

    # 设备状态检查配置
    PING_TIMEOUT = 2
    PING_COUNT = 2

    # 事件驱动监控（SNMP Trap / Syslog / JSON 心跳）配置
    # 默认开启；使用非特权端口，避免需要 root 绑定 162/514。
    # 真实 SNMP Trap 来自网络设备的 UDP 162，需在设备侧或 snmptrapd 转发到 trap_port。
    EVENT_MONITOR_ENABLED = os.environ.get('EVENT_MONITOR_ENABLED', '1') == '1'
    EVENT_MONITOR_TRAP_PORT = int(os.environ.get('EVENT_MONITOR_TRAP_PORT', '9162'))
    EVENT_MONITOR_SYSLOG_PORT = int(os.environ.get('EVENT_MONITOR_SYSLOG_PORT', '9514'))
    
    # 分页配置
    ITEMS_PER_PAGE = 20
    
    # 拓扑配置
    TOPOLOGY_IMAGE_FORMAT = 'png'
    TOPOLOGY_DPI = 100
