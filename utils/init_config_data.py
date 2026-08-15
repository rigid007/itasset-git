import json
from datetime import datetime, timedelta
from models.config_models import (
    SystemSetting, GlobalParameter, LogSetting, Role, Permission
)
from models.models import MonitorSetting
from extensions import db  # 添加这个导入
from flask import current_app  # 添加这个导入
#
# ================== 默认配置数据 ==================

default_system_settings = [
    {"key": "site_name", "value": "资产管理平台", "description": "网站名称"},
    {"key": "maintenance_mode", "value": "false", "description": "维护模式开关"},
    {"key": "contact_email", "value": "admin@example.com", "description": "联系邮箱"},
]

default_roles = [
    {"name": "admin", "description": "系统管理员"},
    {"name": "operator", "description": "普通操作员"},
    {"name": "viewer", "description": "只读用户"},
]

default_permissions = [
    {"name": "manage_users", "description": "管理用户"},
    {"name": "manage_devices", "description": "管理设备"},
    {"name": "view_reports", "description": "查看报表"},
    {"name": "system_config", "description": "系统配置"},
]

# 角色-权限映射（按角色名）
role_permissions_map = {
    "admin": ["manage_users", "manage_devices", "view_reports", "system_config"],
    "operator": ["manage_devices", "view_reports"],
    "viewer": ["view_reports"],
}

default_global_parameters = [
    {"name": "default_location", "value": "总部机房", "description": "默认位置"},
    {"name": "auto_archive_days", "value": "90", "description": "自动归档天数"},
]

default_monitor_settings = [
    {
        "setting_key": "link_stale_ttl_hours",
        "setting_value": "72",
        "setting_type": "number",
        "category": "topology",
        "scope": "global",
        "description": "自动发现链路超过该小时数未被 LLDP 再次确认，则标记为 stale（僵尸链路老化阈值）",
        "enabled": True,
        "is_default": True,
    },
]


default_log_settings = [
    {
        "log_type": "system", "enabled": True, "level": "info",
        "retention_days": 730, "max_file_size": 10, "max_files": 10,
        "output_format": "json",
        "destinations": json.dumps([{"type": "file", "path": "logs/system.log"}]),
        "filters": json.dumps({}),
    },
    {
        "log_type": "audit", "enabled": True, "level": "info",
        "retention_days": 1095, "max_file_size": 10, "max_files": 20,
        "output_format": "json",
        "destinations": json.dumps([{"type": "database"}]),
        "filters": json.dumps({}),
    },
    {
        "log_type": "access", "enabled": True, "level": "info",
        "retention_days": 180, "max_file_size": 5, "max_files": 10,
        "output_format": "json",
        "destinations": json.dumps([{"type": "file", "path": "logs/access.log"}]),
        "filters": json.dumps({}),
    },
    {
        "log_type": "error", "enabled": True, "level": "error",
        "retention_days": 365, "max_file_size": 10, "max_files": 10,
        "output_format": "json",
        "destinations": json.dumps([{"type": "file", "path": "logs/error.log"}, {"type": "email"}]),
        "filters": json.dumps({}),
    },
]


def init_log_settings(db):
    """种子化 4 类日志设置(系统/审计/访问/错误),幂等,可重复调用。"""
    for log_data in default_log_settings:
        existing = db.session.query(LogSetting).filter_by(log_type=log_data["log_type"]).first()
        if not existing:
            db.session.add(LogSetting(**log_data))
    db.session.commit()


# ================== 初始化函数 ==================

def init_config_data(db):
    """
    初始化系统配置数据。
    调用前必须确保：
      - 所有模型已导入
      - 处于 Flask app context 中
      - db 是 Flask-SQLAlchemy 的 db 实例
    """
    print("开始初始化配置数据...")

    # --- 1. 初始化 SystemSetting ---
    for setting_data in default_system_settings:
        existing = db.session.query(SystemSetting).filter_by(key=setting_data["key"]).first()
        if not existing:
            setting = SystemSetting(**setting_data)
            db.session.add(setting)

    # --- 2. 初始化 Permission ---
    permission_map = {}
    for perm_data in default_permissions:
        existing = db.session.query(Permission).filter_by(name=perm_data["name"]).first()
        if not existing:
            perm = Permission(**perm_data)
            db.session.add(perm)
            db.session.flush()  # 获取 ID
            permission_map[perm.name] = perm
        else:
            permission_map[existing.name] = existing

    # --- 3. 初始化 Role 并关联权限 ---
    role_map = {}
    for role_data in default_roles:
        existing = db.session.query(Role).filter_by(name=role_data["name"]).first()
        if not existing:
            role = Role(**role_data)
            db.session.add(role)
            db.session.flush()
            role_map[role.name] = role
        else:
            role_map[existing.name] = existing

    # 关联角色与权限
    for role_name, perm_names in role_permissions_map.items():
        role = role_map.get(role_name)
        if role:
            perms_to_assign = [permission_map[name] for name in perm_names if name in permission_map]
            # 避免重复添加（如果已有关系）
            current_perm_ids = {p.id for p in role.permissions}
            for perm in perms_to_assign:
                if perm.id not in current_perm_ids:
                    role.permissions.append(perm)

    # --- 4. 初始化 GlobalParameter ---
    for param_data in default_global_parameters:
        existing = db.session.query(GlobalParameter).filter_by(name=param_data["name"]).first()
        if not existing:
            param = GlobalParameter(**param_data)
            db.session.add(param)

    # --- 5. 初始化 LogSetting ---
    for log_data in default_log_settings:
        existing = db.session.query(LogSetting).filter_by(module=log_data["module"]).first()
        if not existing:
            log_setting = LogSetting(**log_data)
            db.session.add(log_setting)

    # --- 6. 初始化 MonitorSetting（链路老化 TTL 等） ---
    for ms_data in default_monitor_settings:
        existing = db.session.query(MonitorSetting).filter_by(
            setting_key=ms_data["setting_key"]
        ).first()
        if not existing:
            db.session.add(MonitorSetting(**ms_data))

    # 提交所有更改
    try:
        db.session.commit()
        print("✅ 配置数据初始化完成")
    except Exception as e:
        db.session.rollback()
        print(f"❌ 配置数据初始化失败: {e}")
        raise