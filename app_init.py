from sqlalchemy import text
import json

from extensions import db
from models.models import User
from models.settings_models import SystemConfig
from models.config_models import LogSetting
from utils.init_config_data import init_log_settings


def init_database(app):
    """
    Unified database initialization function.
    Creates tables and seeds initial data.
    """
    with app.app_context():
        print("=== 开始数据库初始化 ===")

        # 1. 创建表
        try:
            db.create_all()
            print("[OK] 所有表创建完成")
        except Exception as e:
            print(f"[ERROR] 创建表失败: {e}")
            db.session.rollback()
            return

        # 2. SQLite WAL 模式设置
        if db.engine.dialect.name == 'sqlite':
            try:
                with db.engine.connect() as conn:
                    conn.execute(text("PRAGMA journal_mode=WAL"))
                    conn.commit()
                print("[OK] 已启用 SQLite WAL 模式")
            except Exception as e:
                print(f"[WARN] 启用 WAL 模式失败: {e}")

        # 3. 创建或更新管理员用户（改进版）
        try:
            admin_user = db.session.query(User).filter_by(username='admin').first()
            if not admin_user:
                print("[INFO] 创建管理员用户...")
                admin_user = User(
                    username='admin',
                    email='rigid@163.com',
                    role='admin',
                    is_active=True
                )
                admin_user.set_password('admin123')
                db.session.add(admin_user)
                db.session.commit()
                print("[OK] 管理员用户创建成功")
                print(f"     用户名: admin")
                print(f"     密码: admin123")
            else:
                print("[INFO] 管理员用户已存在")
                # 可选：重置密码
                # admin_user.set_password('admin123')
                # db.session.commit()
                # print("[OK] 管理员密码已重置")
        except Exception as e:
            print(f"[ERROR] 初始化用户失败: {e}")
            db.session.rollback()
            # 打印详细错误信息
            import traceback
            traceback.print_exc()

        # 4. 系统配置初始化
        try:
            default_configs = [
                {'key': 'site_name', 'value': '资产管理系统', 'description': '站点名称'},
                {'key': 'site_title', 'value': 'IT资产管理系统', 'description': '页面标题'},
                {'key': 'footer_text', 'value': '© 2024 资产管理系统', 'description': '页脚文本'},
                {'key': 'scan_interval', 'value': '300', 'description': '设备扫描间隔(秒)'},
                {'key': 'topology_interval', 'value': '60', 'description': '拓扑检查间隔(秒)'},
                {'key': 'snmp_timeout', 'value': '3', 'description': 'SNMP超时时间(秒)'},
                {'key': 'snmp_retries', 'value': '2', 'description': 'SNMP重试次数'},
            ]
            for config in default_configs:
                existing = db.session.query(SystemConfig).filter_by(key=config['key']).first()
                if not existing:
                    system_config = SystemConfig(
                        key=config['key'],
                        value=config['value'],
                        description=config['description']
                    )
                    db.session.add(system_config)
            db.session.commit()
            print("[OK] 系统配置初始化完成")
        except Exception as e:
            print(f"[ERROR] 系统配置初始化失败: {e}")
            db.session.rollback()


        # 创建默认角色和权限
        try:
            from utils.permission import create_default_roles_and_permissions
            create_default_roles_and_permissions()
            print("[OK] 角色和权限初始化完成")
        except Exception as e:
            print(f"[ERROR] 角色和权限初始化失败: {e}")
            db.session.rollback()

        # 初始化告警通知默认设置
        try:
            from services.notification_service import init_alert_settings
            init_alert_settings()
            print("[OK] 告警通知设置初始化完成")
        except Exception as e:
            print(f"[ERROR] 告警通知设置初始化失败: {e}")
            db.session.rollback()

        # 初始化日志设置(系统/审计/访问/错误)
        try:
            init_log_settings(db)
            print("[OK] 日志设置初始化完成")
        except Exception as e:
            print(f"[ERROR] 日志设置初始化失败: {e}")
            db.session.rollback()
            import traceback
            traceback.print_exc()

        print("[OK] 数据库初始化完成")
