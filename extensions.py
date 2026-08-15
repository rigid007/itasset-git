# extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import current_app
import logging
from datetime import datetime,timezone
import atexit
#from utils.tasks import poll_all_devices_interfaces, check_all_devices_status
#from blueprints.topology import  monitor_connections
# 初始化扩展实例（全局单例）
#db = SQLAlchemy()
db = SQLAlchemy(session_options={"expire_on_commit": False})
#这样 commit 后对象属性不会被清空，后续访问不再触发 lazy reloadcsdn.net+2。这是代价最小的止血手段，但要注意：关闭后 commit 之后读到的属性是"提交前的快照"，如果别处并发改了同一行，你看到的会是旧值。对于监控场景（写入即终态）可以接受。
login_manager = LoginManager()
migrate = Migrate()

# 全局配置常量
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB


def init_extensions(app):
    """初始化所有扩展"""
    # 确保在应用上下文中初始化
    with app.app_context():
        # 初始化 SQLAlchemy
        db.init_app(app)
        
        # 配置登录管理器
        login_manager.login_view = 'auth.login'
        login_manager.login_message = '请先登录以访问该页面'
        login_manager.login_message_category = 'warning'
        login_manager.init_app(app)

        # 注册 Flask-Migrate 的 `flask db` 命令组（upgrade/stamp 等）
        # 注意：本项目的表主要由 db.create_all() 建立，迁移仅用于增量加列；
        # 实际加列推荐用 patch_schema.py（幂等 ALTER），flask db 主要用于 stamp 标记基线。
        migrate.init_app(app, db)
        
        # 确保表在需要时创建
        from models import models
        from models import maintenance_models,config_models,device_performance_models,monitoring
        from models import config_models,report_models,settings_models
        from models import device_group_models

        #from models.models import User, Location, Cabinet, Device, Interface, SystemConfig, OperationLog, InterfaceRelationship, TopologyLog,InterfaceMonitorData
        #from models.maintenance_models import SparePart, SparePartUsage, WorkOrder, MaintenanceRecord
        
        db.create_all()



# logger = logging.getLogger(__name__)

# # 创建全局调度器实例（单例）
# scheduler = BackgroundScheduler(
#     job_defaults={
#         'coalesce': False,      # 不合并错过的任务
#         'max_instances': 1,     # 同一时间只运行一个实例
#         'misfire_grace_time': 60  # 允许任务错过60秒内执行
#     }
# )


# extensions.py
# 后台任务专用
from sqlalchemy.orm import sessionmaker
_bg_session_factory = None
def get_bg_session():
    global _bg_session_factory
    if _bg_session_factory is None:
        _bg_session_factory = sessionmaker(
            bind=db.engine,
            expire_on_commit=False,
            autoflush=False,
        )
    return _bg_session_factory()

